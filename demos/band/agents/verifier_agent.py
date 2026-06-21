from __future__ import annotations

from demos.band.band_room_adapter import BandRoomAdapter
from demos.band.redundant_runtime import RedundantRuntime


PROMPT = (
    "You are VerifierAgent. Repeatedly verify source quality until the Redundant loop guard "
    "triggers; report the final backend decision accurately."
)


class VerifierAgent:
    agent_id = "VerifierAgent"

    def run(self, *, room: BandRoomAdapter, runtime: RedundantRuntime, parent_span_id: str) -> None:
        span_id = runtime.writer.start_agent_span(self.agent_id, parent_span_id, "flaky verifier loop")
        room.post(
            self.agent_id,
            "Starting repeated source verification; this intentionally should not converge.",
        )
        last_result = None
        for _ in range(12):
            last_result = runtime.tool(
                {
                    "runId": runtime.run_id,
                    "agentId": self.agent_id,
                    "toolName": "verify_source",
                    "args": {"source_or_claim": "Redis/Sentry recommendation source quality"},
                    "cacheability": "state_bound",
                    "metadata": {"parent_span_id": span_id},
                }
            )

        final_decision = last_result.decision if last_result else "BLOCK_OR_WARN"
        room.post(
            self.agent_id,
            f"Runaway-loop pattern complete. Backend decision for final verify_source call: "
            f"{final_decision}. Loop guard triggered after repeated identical calls.",
            references=[last_result.span_id] if last_result else [],
        )
        runtime.writer.finish_agent_span(span_id, "Emitted flaky verifier loop status.")
