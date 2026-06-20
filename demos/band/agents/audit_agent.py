from __future__ import annotations

from demos.band.band_room_adapter import BandRoomAdapter
from demos.band.redundant_runtime import LLM_MODEL, RedundantRuntime


PROMPT = (
    "You are AuditAgent. Confirm that the exact cross-agent duplicate is visible across "
    "ResearchAgent, ReportAgent, and AuditAgent."
)


class AuditAgent:
    agent_id = "AuditAgent"

    def run(self, *, room: BandRoomAdapter, runtime: RedundantRuntime, parent_span_id: str) -> None:
        span_id = runtime.writer.start_agent_span(self.agent_id, parent_span_id, "exact duplicate audit")
        note = runtime.llm(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": room.snapshot_context()},
                ],
                "model": LLM_MODEL,
                "metadata": {"purpose": "audit_note", "parent_span_id": span_id},
            }
        )
        room.post(self.agent_id, note.output, references=[note.span_id])
        duplicate = runtime.tool(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "toolName": "search_docs",
                "args": {"query": "agent cost optimization redis sentry"},
                "cacheability": "pure",
                "metadata": {"parent_span_id": span_id},
            }
        )
        room.post(
            self.agent_id,
            f"Audit duplicate check decision: {duplicate.decision}.",
            references=[duplicate.span_id],
        )
        runtime.writer.finish_agent_span(span_id, "Confirmed exact duplicate audit path.")

