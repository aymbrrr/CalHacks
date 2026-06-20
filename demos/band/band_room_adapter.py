from __future__ import annotations

from typing import Protocol


class BandRoomAdapter(Protocol):
    room_id: str

    def post(self, speaker: str, content: str, *, kind: str = "message", references: list[str] | None = None) -> str:
        ...

    def snapshot_context(self) -> str:
        ...

