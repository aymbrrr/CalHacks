from __future__ import annotations

from .trace_writer import TraceWriter


class FallbackBandRoom:
    """Local stand-in for a Band room with the same transcript shape."""

    def __init__(self, writer: TraceWriter, *, echo: bool = True) -> None:
        self.writer = writer
        self.room_id = writer.room_id
        self.echo = echo

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
        if self.echo:
            print(f"[Band:{self.room_id}] {speaker}: {content}")
        return message["message_id"]

    def snapshot_context(self) -> str:
        return "\n".join(
            f"{message['speaker']}: {message['content']}"
            for message in self.writer.messages
        )

