from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from demos.band.agents import AGENT_PROMPTS, AuditAgent, ReportAgent, ResearchAgent, VerifierAgent
from demos.band.band_room_adapter import BandRoomAdapter
from demos.band.redundant_runtime import RedundantRuntime
from demos.band.trace_writer import TraceWriter


try:
    from band.core.simple_adapter import SimpleAdapter
except ImportError:  # Allows local static checks without band-sdk installed.
    class SimpleAdapter:  # type: ignore[no-redef]
        def __init__(self, *, history_converter: Any | None = None, features: Any | None = None) -> None:
            self.history_converter = history_converter
            self.agent_name: str = ""
            self.agent_description: str = ""

        async def on_started(self, agent_name: str, agent_description: str) -> None:
            self.agent_name = agent_name
            self.agent_description = agent_description


TASK = "Research agent cost optimization tools, compare Redis/Sentry-style approaches, and produce a short recommendation."

HUMAN_HANDLE = "julia.m.lu"

# Map friendly agent names (with or without @) to their Band participant handles.
_AGENT_HANDLE_MAP: dict[str, str] = {
    "researchagent": f"{HUMAN_HANDLE}/researchagent",
    "reportagent": f"{HUMAN_HANDLE}/reportagent",
    "auditagent": f"{HUMAN_HANDLE}/auditagent",
    "verifieragent": f"{HUMAN_HANDLE}/verifieragent",
}


def normalize_mentions(mentions: list[str] | None) -> list[str]:
    """Return a non-empty list of Band participant handles.

    Band requires at least one mention for every send_message call.
    If no mentions are provided, defaults to the human user handle.
    """
    if not mentions:
        return [HUMAN_HANDLE]
    resolved: list[str] = []
    for m in mentions:
        key = m.lstrip("@").lower()
        resolved.append(_AGENT_HANDLE_MAP.get(key, m))
    return resolved or [HUMAN_HANDLE]


@dataclass(frozen=True)
class OutboundMessage:
    speaker: str
    content: str
    kind: str
    references: list[str]
    mentions: list[str]


class RealBandDemoState:
    def __init__(self, *, run_id: str, trace_out: Path, store=None) -> None:
        self.run_id = run_id
        self.trace_out = trace_out
        self.writer = TraceWriter(run_id=run_id, mode="real-band", task=TASK)
        self.runtime = RedundantRuntime(run_id=run_id, mode="redundant", writer=self.writer, store=store)
        self.lock = asyncio.Lock()
        self.room_span_id: str | None = None
        self.finished_room = False
        # Maps step name → task hash it was completed for.
        # A step is skipped only when the incoming task hashes to the same value.
        self.completed_steps: dict[str, str] = {}
        self.research_queries: list[str] = []
        self.current_task: str = ""

    def ensure_room_started(self, *, task: str, room_id: str) -> str:
        if self.room_span_id is None:
            self.writer.room_id = f"band-live-{room_id}"
            self.room_span_id = self.writer.start_agent_span("BandRoom", None, task)
            self.writer.add_room_message(speaker="User", content=task, kind="task")
        return self.room_span_id

    def write_trace(self) -> None:
        report = self.runtime.build_report()
        duplicate_clusters = self.runtime.build_duplicate_clusters()
        trace = self.writer.build_trace(
            agent_prompts=AGENT_PROMPTS,
            report=report,
            duplicate_clusters=duplicate_clusters,
            known_fallback_limitations=[
                "Real Band mode uses the Band SDK for room delivery, but still uses deterministic scripted local tools.",
                "The Redundant runtime is the same demo-compatible shim used by fallback mode.",
                "The trace is updated locally as Band messages trigger each remote agent.",
            ],
        )
        trace["run"]["band_adapter"] = "real-band-sdk"
        self.writer.write_trace(self.trace_out, trace)

    def finish_room_once(self) -> None:
        if self.room_span_id and not self.finished_room:
            self.writer.finish_agent_span(self.room_span_id, "Completed real Band SDK multi-agent collaboration.")
            self.finished_room = True


class RealBandRoom(BandRoomAdapter):
    def __init__(
        self,
        *,
        writer: TraceWriter,
        default_speaker: str,
        outbox: list[OutboundMessage],
    ) -> None:
        self.writer = writer
        self.room_id = writer.room_id
        self.default_speaker = default_speaker
        self.outbox = outbox

    def post(
        self,
        speaker: str,
        content: str,
        *,
        kind: str = "message",
        references: list[str] | None = None,
    ) -> str:
        message = self.writer.add_room_message(
            speaker=speaker,
            content=content,
            kind=kind,
            references=references,
        )
        self.outbox.append(
            OutboundMessage(
                speaker=speaker,
                content=content,
                kind=kind,
                references=references or [],
                mentions=[],
            )
        )
        return message["message_id"]

    def queue_handoff(self, *, content: str, mentions: list[str]) -> None:
        self.writer.add_room_message(
            speaker=self.default_speaker,
            content=content,
            kind="handoff",
            references=[],
        )
        self.outbox.append(
            OutboundMessage(
                speaker=self.default_speaker,
                content=content,
                kind="handoff",
                references=[],
                mentions=mentions,
            )
        )

    def snapshot_context(self) -> str:
        return "\n".join(
            f"{message['speaker']}: {message['content']}"
            for message in self.writer.messages
        )


class LocalRedundantBandAdapter(SimpleAdapter):
    def __init__(self, *, agent_name: str, state: RealBandDemoState) -> None:
        super().__init__(history_converter=None)
        self.agent_name = agent_name
        self.state = state

    async def on_started(self, agent_name: str, agent_description: str) -> None:
        await super().on_started(agent_name, agent_description)
        print(f"REAL BAND MODE: {self.agent_name} connected as {agent_name}")

    async def on_message(
        self,
        msg: Any,
        tools: Any,
        history: Any,
        participants_msg: str | None,
        contacts_msg: str | None,
        *,
        is_session_bootstrap: bool,
        room_id: str,
    ) -> None:
        content = getattr(msg, "content", "") or TASK
        print(f"REAL BAND MODE: {self.agent_name} on_message bootstrap={is_session_bootstrap} content={content[:60]!r}")
        async with self.state.lock:
            parent_span_id = self.state.ensure_room_started(task=content, room_id=room_id)
            outbox: list[OutboundMessage] = []
            room = RealBandRoom(
                writer=self.state.writer,
                default_speaker=self.agent_name,
                outbox=outbox,
            )

            if self.agent_name == "ResearchAgent":
                self._run_research(room=room, parent_span_id=parent_span_id, task=content)
            elif self.agent_name == "ReportAgent":
                self._run_report(room=room, parent_span_id=parent_span_id)
            elif self.agent_name == "AuditAgent":
                self._run_audit(room=room, parent_span_id=parent_span_id)
            elif self.agent_name == "VerifierAgent":
                self._run_verifier(room=room, parent_span_id=parent_span_id)
            else:
                room.post(self.agent_name, f"Unknown agent: {self.agent_name}")

            self.state.write_trace()

        await self._flush_outbox(outbox, tools)

    def _run_research(self, *, room: RealBandRoom, parent_span_id: str, task: str) -> None:
        task_hash = hashlib.md5(task.strip().lower().encode()).hexdigest()
        if self.state.completed_steps.get("research") == task_hash:
            room.post("ResearchAgent", "ResearchAgent already completed this research task.")
            return

        # New or different task — reset downstream steps so the full flow reruns.
        if "research" in self.state.completed_steps:
            self.state.completed_steps.clear()

        queries = ResearchAgent().run(room=room, runtime=self.state.runtime, parent_span_id=parent_span_id, task=task)
        self.state.research_queries = queries or []
        self.state.current_task = task
        self.state.completed_steps["research"] = task_hash
        room.queue_handoff(
            content="@ReportAgent please continue by asking the overlapping questions.",
            mentions=["ReportAgent"],
        )

    def _run_report(self, *, room: RealBandRoom, parent_span_id: str) -> None:
        report = ReportAgent()
        if "report_overlap" not in self.state.completed_steps:
            report.run_overlap(room=room, runtime=self.state.runtime, parent_span_id=parent_span_id, task=self.state.current_task, research_queries=self.state.research_queries)
            self.state.completed_steps["report_overlap"] = "done"
            room.queue_handoff(
                content="@AuditAgent please run the exact duplicate audit for the canonical search query.",
                mentions=["AuditAgent"],
            )
            room.queue_handoff(
                content="@VerifierAgent please run the 12-call flaky source verification loop.",
                mentions=["VerifierAgent"],
            )
            return

        if "verifier" in self.state.completed_steps and "report_final" not in self.state.completed_steps:
            report.write_final(room=room, runtime=self.state.runtime, parent_span_id=parent_span_id)
            self.state.completed_steps["report_final"] = "done"
            self.state.finish_room_once()
            return

        room.post("ReportAgent", "ReportAgent is waiting for VerifierAgent before writing the final recommendation.")

    def _run_audit(self, *, room: RealBandRoom, parent_span_id: str) -> None:
        if "audit" in self.state.completed_steps:
            room.post("AuditAgent", "AuditAgent already completed the duplicate audit.")
            return

        AuditAgent().run(room=room, runtime=self.state.runtime, parent_span_id=parent_span_id, research_queries=self.state.research_queries)
        self.state.completed_steps["audit"] = "done"

    def _run_verifier(self, *, room: RealBandRoom, parent_span_id: str) -> None:
        if "verifier" in self.state.completed_steps:
            room.post("VerifierAgent", "VerifierAgent already completed the runaway-loop check.")
            return

        VerifierAgent().run(room=room, runtime=self.state.runtime, parent_span_id=parent_span_id)
        self.state.completed_steps["verifier"] = "done"
        room.queue_handoff(
            content="@ReportAgent VerifierAgent is done; please write the final recommendation.",
            mentions=["ReportAgent"],
        )

    async def _flush_outbox(self, outbox: list[OutboundMessage], tools: Any) -> None:
        for message in outbox:
            await self._send_band_message(tools, message.content, message.mentions)

    async def _send_band_message(self, tools: Any, content: str, mentions: list[str]) -> None:
        resolved = normalize_mentions(mentions)
        print(f"REAL BAND MODE: {self.agent_name} → sending to {resolved}: {content[:60]!r}")
        try:
            await tools.send_message(content, resolved)
            print(f"REAL BAND MODE: {self.agent_name} → send OK")
        except Exception as exc:
            print(f"REAL BAND MODE: {self.agent_name} → send FAILED: {exc!r}")

