from __future__ import annotations

import re

from demos.band.band_room_adapter import BandRoomAdapter
from demos.band.redundant_runtime import LLM_MODEL, RedundantRuntime


PROMPT = (
    "You are ResearchAgent. Use Band room context, call only Redundant-wrapped tools, "
    "post concise findings, and leave useful source references for downstream agents."
)

_QUERY_GEN_PROMPT = (
    "Given the research task below, produce exactly 3 short search queries (one per line, no numbering, "
    "no bullet points) that would surface the most relevant documentation and prior art. "
    "Each query must be under 10 words.\n\nTask: {task}"
)


def _parse_queries(text: str, fallback: str) -> list[str]:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    queries = [re.sub(r"^[\d\.\-\*]+\s*", "", l) for l in lines if len(l) < 120][:3]
    if not queries:
        return [fallback]
    return queries


class ResearchAgent:
    agent_id = "ResearchAgent"

    def run(self, *, room: BandRoomAdapter, runtime: RedundantRuntime, parent_span_id: str, task: str) -> list[str]:
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

        # Generate task-specific search queries instead of using hardcoded strings.
        query_result = runtime.llm(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "messages": [
                    {"role": "system", "content": "You generate concise search queries. Output only the queries, one per line."},
                    {"role": "user", "content": _QUERY_GEN_PROMPT.format(task=task)},
                ],
                "model": LLM_MODEL,
                "metadata": {"purpose": "query_generation", "parent_span_id": span_id},
            }
        )
        queries = _parse_queries(query_result.output, task[:80])
        while len(queries) < 3:
            queries.append(queries[-1])

        tool_results = [
            runtime.tool(
                {
                    "runId": runtime.run_id,
                    "agentId": self.agent_id,
                    "toolName": "search_docs",
                    "args": {"query": q},
                    "cacheability": "pure",
                    "metadata": {"parent_span_id": span_id},
                }
            )
            for q in queries
        ]

        scan = runtime.tool(
            {
                "runId": runtime.run_id,
                "agentId": self.agent_id,
                "toolName": "scan_repo",
                "args": {"topic": queries[0][:50]},
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
                        "content": f"Task: {task}\n\nResearch results:\n"
                        + "\n".join(r.output for r in tool_results)
                        + "\n"
                        + scan.output,
                    },
                ],
                "model": LLM_MODEL,
                "metadata": {"purpose": "research_findings", "parent_span_id": span_id},
            }
        )
        room.post(
            self.agent_id,
            findings.output,
            references=[r.span_id for r in tool_results] + [scan.span_id],
        )
        runtime.writer.finish_agent_span(span_id, "Posted research plan and findings.")
        return queries
