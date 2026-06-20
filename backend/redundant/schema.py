"""Schema: enums + pydantic models matching the UI/Backend Contract.

Field names are kept identical to docs/redundant-plan.md so the UI (Chunk 4) can
consume events and reports without any translation layer.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, PrivateAttr


class CallType(str, Enum):
    LLM = "llm"
    TOOL = "tool"


class Cacheability(str, Enum):
    PURE = "pure"
    FRESHNESS_SENSITIVE = "freshness_sensitive"
    STATE_BOUND = "state_bound"
    SIDE_EFFECTING = "side_effecting"


class Decision(str, Enum):
    EXECUTE = "EXECUTE"
    EXACT_REUSE = "EXACT_REUSE"
    SEMANTIC_REUSE = "SEMANTIC_REUSE"
    COMPRESS_AND_EXECUTE = "COMPRESS_AND_EXECUTE"
    BLOCK_OR_WARN = "BLOCK_OR_WARN"


REUSE_DECISIONS = {Decision.EXACT_REUSE, Decision.SEMANTIC_REUSE}
# Decisions that count as "reused or blocked" (i.e. did not run fresh) for the report.
NON_EXECUTED_DECISIONS = {
    Decision.EXACT_REUSE,
    Decision.SEMANTIC_REUSE,
    Decision.BLOCK_OR_WARN,
}


class CallRecord(BaseModel):
    """The Required Call Schema (docs/redundant-plan.md). One per intercepted call."""

    call_id: str
    run_id: str
    agent_id: str
    call_type: CallType
    tool_name: str
    cacheability: Cacheability
    normalized_input: str
    input_hash: str
    embedding: Optional[list[float]] = None
    output: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    created_at: str
    state_fingerprint: Optional[str] = None
    decision: Decision = Decision.EXECUTE
    reuse_source_call_id: Optional[str] = None
    verifier_score: Optional[float] = None
    explanation: str = ""


class RedundantEvent(BaseModel):
    """Live event emitted to Redis Streams and surfaced to the UI."""

    event_id: str
    run_id: str
    ts: str
    agent_id: str
    call_id: str
    call_type: CallType
    tool_name: str
    decision: Decision
    cacheability: Cacheability
    summary: str
    explanation: str
    saved_cost_usd: float = 0.0
    saved_latency_ms: int = 0
    saved_tokens: int = 0
    # Real cost actually spent on this call (0 for pure reuse/block). Optional in
    # the contract — the UI ignores it; the report uses it to compute actual spend.
    actual_cost_usd: float = 0.0
    source_call_id: Optional[str] = None
    verifier_score: Optional[float] = None
    cluster_id: Optional[str] = None
    sponsor_hooks: list[str] = Field(default_factory=list)

    # In-process side channel: the call's output for direct callers (e.g. Band
    # agents). Never serialized into the streamed JSON.
    _output: Optional[str] = PrivateAttr(default=None)

    @property
    def output(self) -> Optional[str]:
        return self._output


class Run(BaseModel):
    run_id: str
    task: str
    mode: str  # "baseline" | "redundant" | "replay"
    status: str  # "idle" | "running" | "complete" | "failed"
    started_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None


class DuplicateCluster(BaseModel):
    cluster_id: str
    label: str
    calls: int
    unique_needed: int
    waste_percent: float
    saved_cost_usd: float
    saved_latency_ms: int
    agent_ids: list[str] = Field(default_factory=list)


class SuggestedFix(BaseModel):
    fix_id: str
    title: str
    description: str
    sponsor_hook: Optional[str] = None
    code_hint: Optional[str] = None


class RunReport(BaseModel):
    run_id: str
    attempted_calls: int
    executed_calls: int
    reused_or_blocked_calls: int
    redundant_rate: float
    estimated_baseline_cost_usd: float
    actual_cost_usd: float
    saved_cost_usd: float
    saved_latency_ms: int
    saved_tokens: int
    worst_duplicate_cluster: Optional[str] = None
    clusters: list[DuplicateCluster] = Field(default_factory=list)
    fixes: list[SuggestedFix] = Field(default_factory=list)
