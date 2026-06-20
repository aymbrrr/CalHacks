from __future__ import annotations

from demos.band.band_room_adapter import BandRoomAdapter
from demos.band.redundant_runtime import LLM_MODEL, RedundantRuntime
from demos.band.scripted_tools import SAME_SOURCE


PROMPT = (
    "You are ResearchAgent. Use Band room context, call only Redundant-wrapped tools, "
    "post concise findings, and leave useful source references for downstream agents."
)


class ResearchAgent:
    agent_id = "ResearchAgent"

    def run(self, *, room: BandRoomAdapter, runtime: RedundantRuntime, parent_span_id: str, task: str) -> None:
        span_id = runtime.writer.start_agent_span(self.agent_id, parent_span_id, task)

        plan = runtime.llm(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": task},
                ],
                "model": LLM_MODEL,
                "metadata": {"purpose": "research_plan", "parent_span_id": span_id},
            }
        )
        room.post(self.agent_id, plan.output, references=[plan.span_id])

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
        langchain = runtime.tool(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "toolName": "search_docs",
                "args": {"query": "LangChain agent tracing cost optimization"},
                "cacheability": "pure",
                "metadata": {"parent_span_id": span_id},
            }
        )
        scan = runtime.tool(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "toolName": "scan_repo",
                "args": {"topic": "cached tool wrapper"},
                "cacheability": "pure",
                "metadata": {"parent_span_id": span_id},
            }
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
        unsafe_seed = runtime.tool(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "toolName": "search_docs",
                "args": {"query": "Redis cache invalidation strategies for agent tool calls"},
                "cacheability": "pure",
                "metadata": {"parent_span_id": span_id},
            }
        )

        findings = runtime.llm(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {
                        "role": "user",
                        "content": "\n".join(
                            [
                                exact.output,
                                langchain.output,
                                scan.output,
                                summary.output,
                                unsafe_seed.output,
                            ]
                        ),
                    },
                ],
                "model": LLM_MODEL,
                "metadata": {"purpose": "research_findings", "parent_span_id": span_id},
            }
        )
        room.post(
            self.agent_id,
            findings.output,
            references=[exact.span_id, langchain.span_id, scan.span_id, summary.span_id, unsafe_seed.span_id],
        )
        runtime.writer.finish_agent_span(span_id, "Posted research plan and findings to Band.")

