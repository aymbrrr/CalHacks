from __future__ import annotations

from demos.band.band_room_adapter import BandRoomAdapter
from demos.band.redundant_runtime import LLM_MODEL, RedundantRuntime
from demos.band.scripted_tools import SAME_SOURCE


PROMPT = (
    "You are ReportAgent. Read Band room context, deliberately ask overlapping questions, "
    "reuse safe Redundant results, and write the final recommendation."
)


class ReportAgent:
    agent_id = "ReportAgent"

    def run_overlap(self, *, room: BandRoomAdapter, runtime: RedundantRuntime, parent_span_id: str, task: str) -> None:
        span_id = runtime.writer.start_agent_span(self.agent_id, parent_span_id, "overlap request")
        request = runtime.llm(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": room.snapshot_context()},
                ],
                "model": LLM_MODEL,
                "metadata": {"purpose": "report_overlap_request", "parent_span_id": span_id},
            }
        )
        room.post(self.agent_id, request.output, references=[request.span_id])

        exact = runtime.tool(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "toolName": "search_docs",
                "args": {"query": "agent cost optimization redis sentry"},
                "cacheability": "pure",
                "metadata": {"parent_span_id": span_id},
            }
        )
        if exact.decision == "EXACT_REUSE" and exact.source_agent_name == "ResearchAgent":
            room.post(
                self.agent_id,
                "ReportAgent reused ResearchAgent's prior result.",
                references=[exact.span_id, exact.source_call_id] if exact.source_call_id else [exact.span_id],
            )

        semantic = runtime.tool(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "toolName": "scan_repo",
                "args": {"topic": "tool cache decorator"},
                "cacheability": "pure",
                "metadata": {"parent_span_id": span_id},
            }
        )
        if semantic.decision == "SEMANTIC_REUSE":
            room.post(
                self.agent_id,
                "Semantic reuse accepted for the tool cache decorator scan.",
                references=[semantic.span_id, semantic.source_call_id] if semantic.source_call_id else [semantic.span_id],
            )

        summary = runtime.tool(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "toolName": "summarize_page",
                "args": {"url_or_text": SAME_SOURCE},
                "cacheability": "pure",
                "metadata": {"parent_span_id": span_id},
            }
        )
        unsafe = runtime.tool(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "toolName": "search_docs",
                "args": {"query": "Sentry alert routing strategies for runaway agents"},
                "cacheability": "pure",
                "metadata": {"parent_span_id": span_id},
            }
        )
        if unsafe.decision == "BLOCK_OR_WARN":
            room.post(
                self.agent_id,
                "Verifier blocked unsafe semantic reuse; executing the Sentry-specific search instead.",
                references=[unsafe.span_id, unsafe.source_call_id] if unsafe.source_call_id else [unsafe.span_id],
            )

        compare = runtime.tool(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "toolName": "compare_tools",
                "args": {"tool_a": "Redis", "tool_b": "Sentry"},
                "cacheability": "pure",
                "metadata": {"parent_span_id": span_id},
            }
        )
        room.post(
            self.agent_id,
            "Overlap check complete; I have exact reuse, semantic reuse, an unsafe block, and the Redis/Sentry comparison.",
            references=[exact.span_id, semantic.span_id, summary.span_id, unsafe.span_id, compare.span_id],
        )
        runtime.writer.finish_agent_span(span_id, "Completed overlapping report research.")

    def write_final(self, *, room: BandRoomAdapter, runtime: RedundantRuntime, parent_span_id: str) -> None:
        span_id = runtime.writer.start_agent_span(self.agent_id, parent_span_id, "final recommendation")
        final = runtime.llm(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": room.snapshot_context()},
                ],
                "model": LLM_MODEL,
                "metadata": {"purpose": "final_recommendation", "parent_span_id": span_id},
            }
        )
        room.post(self.agent_id, final.output, kind="final", references=[final.span_id])
        runtime.writer.finish_agent_span(span_id, "Posted final recommendation.")

