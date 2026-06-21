from __future__ import annotations

from demos.band.band_room_adapter import BandRoomAdapter
from demos.band.redundant_runtime import LLM_MODEL, RedundantRuntime


PROMPT = (
    "You are AuditAgent. You deliberately repeat the canonical search query that ResearchAgent "
    "already executed and ReportAgent already reused. The backend decision for your own call is "
    "provided in the message. Report ONLY what the backend decided: EXACT_REUSE means the "
    "normalized hash matched a cached result; BLOCK_OR_WARN means the redundant loop guard "
    "triggered (3+ identical calls). Do not infer 'exact' or 'identical' from text similarity "
    "alone — base your summary solely on the backend decision provided."
)


class AuditAgent:
    agent_id = "AuditAgent"

    def run(self, *, room: BandRoomAdapter, runtime: RedundantRuntime, parent_span_id: str, research_queries: list[str] | None = None) -> None:
        span_id = runtime.writer.start_agent_span(self.agent_id, parent_span_id, "exact duplicate audit")

        # Reuse the same query as ResearchAgent and ReportAgent to trigger the loop guard.
        audit_query = (research_queries or ["agent cost optimization"])[0]
        duplicate = runtime.tool(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "toolName": "search_docs",
                "args": {"query": audit_query},
                "cacheability": "pure",
                "metadata": {"parent_span_id": span_id},
            }
        )
        note = runtime.llm(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Backend decision for this duplicate search_docs call: {duplicate.decision}.\n"
                            f"Room context:\n{room.snapshot_context()}"
                        ),
                    },
                ],
                "model": LLM_MODEL,
                "metadata": {"purpose": "audit_note", "parent_span_id": span_id},
            }
        )
        room.post(self.agent_id, note.output, references=[note.span_id])
        room.post(
            self.agent_id,
            f"Audit duplicate check decision: {duplicate.decision}.",
            references=[duplicate.span_id],
        )
        runtime.writer.finish_agent_span(span_id, "Confirmed exact duplicate audit path.")

