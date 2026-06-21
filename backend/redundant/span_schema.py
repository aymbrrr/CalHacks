"""Span + Finding data contracts per DESIGN_redis.md §6."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class TokenCost(BaseModel):
    input: int = 0
    output: int = 0


class Span(BaseModel):
    span_id: str
    parent_span_id: Optional[str] = None
    kind: str  # "agent" | "llm" | "tool"
    name: str
    tool_name: Optional[str] = None
    agent_name: str = "default"
    input: str = ""
    output: str = ""
    input_hash: str = ""
    start_time: int = 0   # epoch ms
    end_time: int = 0
    tokens: TokenCost = Field(default_factory=TokenCost)
    model: Optional[str] = None
    # Stamped during trace ingest from (model, tokens). Pre-computing here keeps
    # every downstream consumer (findings, UI flamegraph, report) reconciled to
    # the same number instead of re-deriving and drifting.
    cost_usd: float = 0.0
    # Firewall decision for this call (EXECUTE | EXACT_REUSE | SEMANTIC_REUSE |
    # COMPRESS_AND_EXECUTE | BLOCK_OR_WARN). None for agent spans / legacy traces.
    # Carries decision context to the UI and lets _stamp_cost leave non-executed
    # calls at ~0 instead of re-deriving a token cost they never incurred.
    decision: Optional[str] = None


class Evidence(BaseModel):
    similarity: Optional[float] = None
    cycle_path: Optional[list[str]] = None
    convergence: str = "unknown"  # "none" | "partial" | "converged" | "unknown"


class Finding(BaseModel):
    finding_id: str
    type: str  # "repetition" | "cycle" | "semantic_duplicate"
    span_ids: list[str]
    representative_span_id: str
    count: int
    description: str
    token_cost: TokenCost
    dollar_cost: float
    severity: str  # "wasteful" | "runaway"
    route: str     # "cache" | "alert"
    cacheable: bool
    evidence: Evidence = Field(default_factory=Evidence)
    # Set True once the Sentry arm has fired an incident for this finding (SR-8).
    alert_fired: bool = False
    # Distinct model strings across this finding's spans. Drives the UI root-
    # cause panel "models" row and provider-aware fix ordering.
    models_involved: list[str] = Field(default_factory=list)
