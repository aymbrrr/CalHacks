"""Runtime wrappers: redundant.tool() and redundant.llm().

Orchestrates the full path for every intercepted call:
  normalize -> exact lookup -> embed + KNN -> decide -> execute or reuse
  -> persist (exact cache + vector index) -> emit event.

EXECUTE / COMPRESS_AND_EXECUTE are the only paths that make a real call.
All decisions are emitted to Redis Streams for the live UI and rolled into the
RunReport.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from redundant.config import SETTINGS, Settings
from redundant.compressor import Compressor, PassthroughCompressor
from redundant.decision import DecisionInput, decide, DecisionResult
from redundant.embeddings import embed_list
from redundant.estimate import (
    count_tokens,
    count_message_tokens,
    estimate_cost,
    default_latency_ms,
    savings_from_reuse,
)
from redundant.normalize import (
    normalize_tool_args,
    normalize_messages,
    compute_hash,
    scope_key,
)
from redundant.redis_store import RedisStore
from redundant.schema import (
    Cacheability,
    CallRecord,
    CallType,
    Decision,
    RedundantEvent,
)
from redundant.tools import default_cacheability, run_tool
from redundant.verifier import Verifier, ThresholdVerifier


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


SPONSOR_HOOKS_BY_DECISION = {
    Decision.EXACT_REUSE: ["Redis"],
    Decision.SEMANTIC_REUSE: ["Redis", "Terac"],
    Decision.COMPRESS_AND_EXECUTE: ["Token Company", "OpenAI"],
    Decision.BLOCK_OR_WARN: ["Sentry"],
    Decision.EXECUTE: ["OpenAI"],
}


class Redundant:
    def __init__(
        self,
        run_id: str,
        store: RedisStore | None = None,
        settings: Settings = SETTINGS,
        verifier: Verifier | None = None,
        compressor: Compressor | None = None,
        openai_client: Any | None = None,
        enabled: bool = True,
    ):
        self.run_id = run_id
        self.s = settings
        self.store = store or RedisStore(settings)
        self.verifier = verifier or ThresholdVerifier(settings)
        self.compressor = compressor or PassthroughCompressor()
        self._openai = openai_client
        # When disabled (baseline mode) the firewall always executes, so the UI
        # can contrast raw spend against the Redundant-enabled run.
        self.enabled = enabled
        try:
            self.store.ensure_index()
        except Exception:
            # Index creation requires RediSearch; tolerate absence so pure paths run.
            pass

    # --- public API ---------------------------------------------------------
    def tool(
        self,
        agent_id: str,
        tool_name: str,
        args: dict[str, Any] | None = None,
        cacheability: str | None = None,
        metadata: dict | None = None,
    ) -> RedundantEvent:
        args = args or {}
        cache = cacheability or default_cacheability(tool_name).value
        normalized = normalize_tool_args(tool_name, args)
        in_tokens = count_tokens(normalized)
        return self._handle(
            agent_id=agent_id,
            call_type=CallType.TOOL,
            tool_name=tool_name,
            cacheability=cache,
            normalized=normalized,
            input_tokens=in_tokens,
            state_fingerprint=(metadata or {}).get("state_fingerprint"),
            execute=lambda: run_tool(tool_name, args),
            model=None,
        )

    def llm(
        self,
        agent_id: str,
        messages: list[dict[str, Any]],
        model: str | None = None,
        cacheability: str = "pure",
        metadata: dict | None = None,
    ) -> RedundantEvent:
        model = model or self.s.default_model
        normalized = normalize_messages(messages, model)
        in_tokens = count_message_tokens(messages)
        return self._handle(
            agent_id=agent_id,
            call_type=CallType.LLM,
            tool_name="llm",
            cacheability=cacheability,
            normalized=normalized,
            input_tokens=in_tokens,
            state_fingerprint=(metadata or {}).get("state_fingerprint"),
            execute=lambda msgs=messages: self._call_openai(msgs, model),
            model=model,
            compress_messages=messages,
        )

    # --- core orchestration -------------------------------------------------
    def _handle(
        self,
        agent_id: str,
        call_type: CallType,
        tool_name: str,
        cacheability: str,
        normalized: str,
        input_tokens: int,
        state_fingerprint: Optional[str],
        execute,
        model: Optional[str],
        compress_messages: Optional[list[dict[str, Any]]] = None,
    ) -> RedundantEvent:
        scope = scope_key(self.run_id, cacheability, state_fingerprint)
        input_hash = compute_hash(scope, normalized)
        call_id = str(uuid.uuid4())

        # Baseline mode: firewall off — always execute, no reuse/savings. Skip the
        # embedding entirely (it would be an unused, possibly paid, OpenAI call).
        if not self.enabled:
            return self._finalize(
                decision=DecisionResult(Decision.EXECUTE, "Baseline run: firewall disabled."),
                agent_id=agent_id, call_id=call_id, call_type=call_type, tool_name=tool_name,
                cacheability=cacheability, normalized=normalized, input_hash=input_hash,
                input_tokens=input_tokens, embedding=None, scope=scope,
                state_fingerprint=state_fingerprint, model=model, exact=None,
                candidates=[], execute=execute, compress_messages=compress_messages,
            )

        embedding = embed_list(normalized, self.s)

        # Lookups.
        exact = self.store.get_exact(scope, input_hash)
        loop_count = self.store.incr_loop(self.run_id, input_hash)

        candidates = []
        try:
            raw = self.store.knn_search(scope, embedding, k=5)
        except Exception:
            raw = []
        exact_id = exact.call_id if exact else None
        is_side_effecting = cacheability == Cacheability.SIDE_EFFECTING.value
        for c in raw:
            if c.call_id == exact_id:
                continue
            cand_is_side = c.cacheability == Cacheability.SIDE_EFFECTING.value
            # A non-side-effecting call must never reuse a side-effect's output;
            # a side-effecting call only matches other side-effects (for warnings).
            if is_side_effecting != cand_is_side:
                continue
            candidates.append(c)

        decision = decide(
            DecisionInput(
                cacheability=cacheability,
                input_tokens=input_tokens,
                exact_hit_call_id=exact_id,
                semantic_candidates=candidates,
                hash_attempt_count=loop_count,
                prior_side_effect_exists=bool(candidates),
            ),
            verifier=self.verifier,
            settings=self.s,
        )

        return self._finalize(
            decision=decision,
            agent_id=agent_id,
            call_id=call_id,
            call_type=call_type,
            tool_name=tool_name,
            cacheability=cacheability,
            normalized=normalized,
            input_hash=input_hash,
            input_tokens=input_tokens,
            embedding=embedding,
            scope=scope,
            state_fingerprint=state_fingerprint,
            model=model,
            exact=exact,
            candidates=candidates,
            execute=execute,
            compress_messages=compress_messages,
        )

    def _finalize(
        self, decision: DecisionResult, agent_id, call_id, call_type, tool_name,
        cacheability, normalized, input_hash, input_tokens, embedding, scope,
        state_fingerprint, model, exact, candidates, execute, compress_messages=None,
    ) -> RedundantEvent:
        d = decision.decision
        output: Optional[str] = None
        out_tokens = 0
        latency_ms = 0
        actual_cost = 0.0
        saved = {"saved_cost_usd": 0.0, "saved_latency_ms": 0, "saved_tokens": 0}

        # Source record (for reuse savings + returned output).
        source: Optional[CallRecord] = exact
        if d in (Decision.EXACT_REUSE, Decision.SEMANTIC_REUSE):
            # Reuse: no execution. Savings == avoided executed cost.
            if source is not None:
                output = source.output
                saved = savings_from_reuse(source.cost_usd, source.latency_ms,
                                           source.input_tokens + source.output_tokens)
            else:
                # Semantic reuse: output carried on the matched Candidate.
                match = next((c for c in candidates if c.call_id == decision.source_call_id), None)
                output = match.output if match else "[reused semantic result]"
                est_cost = estimate_cost(model or self.s.default_model, input_tokens, input_tokens // 2)
                saved = savings_from_reuse(est_cost, default_latency_ms(call_type.value),
                                           input_tokens + input_tokens // 2)
        elif d == Decision.BLOCK_OR_WARN:
            # Blocked: nothing executed. Credit the avoided cost as saved.
            est_cost = estimate_cost(model or self.s.default_model, input_tokens, input_tokens // 2)
            saved = savings_from_reuse(est_cost, default_latency_ms(call_type.value),
                                       input_tokens + input_tokens // 2)
        else:
            # EXECUTE or COMPRESS_AND_EXECUTE: do the real work and measure.
            messages_in_tokens = input_tokens
            exec_fn = execute
            if (d == Decision.COMPRESS_AND_EXECUTE and call_type == CallType.LLM
                    and compress_messages is not None):
                # Compression seam (Chunk 4 / Token Company). Compress the bloated
                # context before executing and credit the avoided input tokens.
                comp = self.compressor.compress(compress_messages)
                messages_in_tokens = comp.tokens_after
                saved["saved_tokens"] += comp.saved_tokens
                exec_fn = lambda msgs=comp.messages: self._call_openai(msgs, model or self.s.default_model)
            start = datetime.now(timezone.utc)
            output = exec_fn()
            latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000) or \
                default_latency_ms(call_type.value)
            out_tokens = count_tokens(output or "")
            actual_cost = estimate_cost(model or self.s.default_model, messages_in_tokens, out_tokens)

        # Persist the new call record (exact cache + vector index) unless blocked.
        record = CallRecord(
            call_id=call_id, run_id=self.run_id, agent_id=agent_id, call_type=call_type,
            tool_name=tool_name, cacheability=Cacheability(cacheability),
            normalized_input=normalized, input_hash=input_hash, embedding=embedding,
            output=output, input_tokens=input_tokens, output_tokens=out_tokens,
            cost_usd=actual_cost, latency_ms=latency_ms or default_latency_ms(call_type.value),
            created_at=_now(), state_fingerprint=state_fingerprint, decision=d,
            reuse_source_call_id=decision.source_call_id, verifier_score=decision.verifier_score,
            explanation=decision.explanation,
        )
        # Baseline mode (firewall off) never writes to the cache/index: it only
        # measures raw spend and must not seed reuse for later runs.
        if self.enabled and d in (Decision.EXECUTE, Decision.COMPRESS_AND_EXECUTE):
            try:
                self.store.put_exact(scope, record)
                self.store.index_call(scope, record)
            except Exception:
                pass

        # Cluster id groups duplicates by normalized hash so the report can show
        # "web/repo search" style clusters.
        cluster_id = f"cl:{input_hash[:12]}"

        event = RedundantEvent(
            event_id="pending", run_id=self.run_id, ts=_now(), agent_id=agent_id,
            call_id=call_id, call_type=call_type, tool_name=tool_name, decision=d,
            cacheability=Cacheability(cacheability),
            summary=_summary(d, agent_id, tool_name, decision.source_call_id),
            explanation=decision.explanation,
            saved_cost_usd=saved["saved_cost_usd"], saved_latency_ms=saved["saved_latency_ms"],
            saved_tokens=saved["saved_tokens"], actual_cost_usd=actual_cost,
            source_call_id=decision.source_call_id, verifier_score=decision.verifier_score,
            cluster_id=cluster_id, sponsor_hooks=SPONSOR_HOOKS_BY_DECISION.get(d, []),
        )
        try:
            event.event_id = self.store.emit_event(event)
        except Exception:
            event.event_id = call_id
        # Attach output for in-process callers (e.g. Band agents) without bloating
        # the streamed JSON.
        event._output = output
        return event

    def _call_openai(self, messages: list[dict[str, Any]], model: str) -> str:
        if self._openai is None:
            from openai import OpenAI

            self._openai = OpenAI(api_key=self.s.openai_api_key)
        resp = self._openai.chat.completions.create(
            model=model, max_tokens=1024, messages=messages,
        )
        return resp.choices[0].message.content or ""


def _summary(decision: Decision, agent_id: str, tool_name: str, source: Optional[str]) -> str:
    if decision == Decision.EXACT_REUSE:
        return f"{agent_id} reused an exact prior {tool_name} result."
    if decision == Decision.SEMANTIC_REUSE:
        return f"{agent_id} reused a semantically-matched {tool_name} result."
    if decision == Decision.BLOCK_OR_WARN:
        return f"{agent_id} blocked a redundant/looping {tool_name} call."
    if decision == Decision.COMPRESS_AND_EXECUTE:
        return f"{agent_id} compressed a bloated {tool_name} call before executing."
    return f"{agent_id} executed {tool_name}."
