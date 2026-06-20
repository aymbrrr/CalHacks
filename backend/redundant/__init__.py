"""Redundant — runtime firewall for multi-agent AI apps (Chunk 1: Runtime + Redis Core).

Public entrypoints::

    from redundant.runtime import Redundant
    redundant = Redundant(run_id="demo-run-001")
    redundant.tool(agent_id="research-agent", tool_name="search_docs", args={...})
    redundant.llm(agent_id="report-agent", messages=[...], model="claude-haiku-4-5")
"""

from redundant.schema import (
    CallType,
    Cacheability,
    Decision,
    CallRecord,
    RedundantEvent,
    Run,
    RunReport,
    DuplicateCluster,
    SuggestedFix,
)

__all__ = [
    "CallType",
    "Cacheability",
    "Decision",
    "CallRecord",
    "RedundantEvent",
    "Run",
    "RunReport",
    "DuplicateCluster",
    "SuggestedFix",
]
