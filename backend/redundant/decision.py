"""Pure decision engine.

Given the result of cache lookups (exact hit + semantic candidates) and call
metadata, choose exactly one Decision. No Redis or network calls live here, so
every branch is unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from redundant.config import SETTINGS, Settings
from redundant.schema import Cacheability, Decision
from redundant.verifier import Candidate, Verifier, ThresholdVerifier


@dataclass
class DecisionInput:
    cacheability: str
    input_tokens: int
    # Exact cache hit (already TTL-checked by the store; None => miss/stale).
    exact_hit_call_id: Optional[str] = None
    # Semantic candidates sorted best-first.
    semantic_candidates: list[Candidate] = None  # type: ignore[assignment]
    # How many times this exact hash has been attempted in this run (loop guard).
    hash_attempt_count: int = 1
    # Whether a *similar prior side-effect* exists (drives the warning).
    prior_side_effect_exists: bool = False

    def __post_init__(self):
        if self.semantic_candidates is None:
            self.semantic_candidates = []


@dataclass
class DecisionResult:
    decision: Decision
    explanation: str
    source_call_id: Optional[str] = None
    verifier_score: Optional[float] = None


def decide(
    inp: DecisionInput,
    verifier: Verifier | None = None,
    settings: Settings = SETTINGS,
) -> DecisionResult:
    verifier = verifier or ThresholdVerifier(settings)
    cache = inp.cacheability

    # 1. Side-effecting: never auto-replay. Warn only if a similar one happened.
    if cache == Cacheability.SIDE_EFFECTING.value:
        if inp.prior_side_effect_exists or inp.exact_hit_call_id or inp.semantic_candidates:
            return DecisionResult(
                Decision.BLOCK_OR_WARN,
                "Similar side-effect action already happened; do not replay automatically.",
                source_call_id=inp.exact_hit_call_id
                or (inp.semantic_candidates[0].call_id if inp.semantic_candidates else None),
            )
        return DecisionResult(Decision.EXECUTE, "Side-effecting call; executing once.")

    # 2. Loop detection: same hash hammered repeatedly within a run.
    if inp.hash_attempt_count >= settings.loop_threshold:
        return DecisionResult(
            Decision.BLOCK_OR_WARN,
            f"Loop detected: identical call attempted {inp.hash_attempt_count}x in this run.",
            source_call_id=inp.exact_hit_call_id,
        )

    # 3. Exact reuse.
    if inp.exact_hit_call_id:
        return DecisionResult(
            Decision.EXACT_REUSE,
            "Exact normalized call already executed in this run scope.",
            source_call_id=inp.exact_hit_call_id,
        )

    # 4. Semantic reuse, gated by the verifier.
    best: Candidate | None = inp.semantic_candidates[0] if inp.semantic_candidates else None
    if best is not None:
        result = verifier.score(cache, best)
        if result.approved:
            return DecisionResult(
                Decision.SEMANTIC_REUSE,
                f"Semantic match approved ({result.reason}).",
                source_call_id=best.call_id,
                verifier_score=result.score,
            )
        # 5. Unsafe to reuse, but bloated -> compress then execute.
        if inp.input_tokens >= settings.bloat_token_threshold:
            return DecisionResult(
                Decision.COMPRESS_AND_EXECUTE,
                f"Reuse unsafe ({result.reason}); prompt bloated, compressing before execute.",
                source_call_id=best.call_id,
                verifier_score=result.score,
            )
        # else fall through to execute, but remember why we didn't reuse.
        return DecisionResult(
            Decision.EXECUTE,
            f"Semantic candidate found but not safe to reuse ({result.reason}).",
            source_call_id=best.call_id,
            verifier_score=result.score,
        )

    # 6. No candidate at all; bloated unsafe miss still benefits from compression.
    if inp.input_tokens >= settings.bloat_token_threshold:
        return DecisionResult(
            Decision.COMPRESS_AND_EXECUTE,
            "No safe duplicate; prompt bloated, compressing before execute.",
        )

    return DecisionResult(Decision.EXECUTE, "No safe duplicate found.")
