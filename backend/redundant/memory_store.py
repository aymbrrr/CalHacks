"""In-memory store mirroring RedisStore's interface.

Used for offline tests and the demo replay fallback (so the product still runs if
Redis Cloud / sponsor APIs are unavailable). KNN is brute-force cosine over the
in-process call set. Not for production — RedisStore is the real backend.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Optional

from redundant.config import SETTINGS, Settings, ttl_for
from redundant.embeddings import cosine_similarity
from redundant.schema import Cacheability, CallRecord, RedundantEvent, Run
from redundant.verifier import Candidate


class _Expiring:
    __slots__ = ("value", "expires_at")

    def __init__(self, value, ttl: int | None):
        self.value = value
        self.expires_at = (time.time() + ttl) if ttl else None

    def alive(self) -> bool:
        return self.expires_at is None or time.time() < self.expires_at


class InMemoryStore:
    def __init__(self, settings: Settings = SETTINGS):
        self.s = settings
        self._exact: dict[str, _Expiring] = {}
        self._loops: dict[str, int] = defaultdict(int)
        self._calls: dict[str, tuple[str, CallRecord]] = {}  # call_id -> (scope, record)
        self._streams: dict[str, list[tuple[str, RedundantEvent]]] = defaultdict(list)
        self._runs: dict[str, Run] = {}
        self._seq = 0
        # Guards all mutable state: the API runs each demo in a daemon thread, so
        # concurrent runs would otherwise race on _seq / _streams / caches.
        self._lock = threading.RLock()

    def ping(self) -> bool:
        return True

    def ensure_index(self) -> None:
        return None

    # --- exact cache --------------------------------------------------------
    def put_exact(self, scope_key: str, record: CallRecord) -> None:
        ttl = ttl_for(record.cacheability.value, self.s)
        if ttl is None:
            return
        with self._lock:
            self._exact[f"{scope_key}:{record.input_hash}"] = _Expiring(record, ttl)

    def get_exact(self, scope_key: str, input_hash: str) -> Optional[CallRecord]:
        with self._lock:
            item = self._exact.get(f"{scope_key}:{input_hash}")
            if item is None:
                return None
            if not item.alive():
                del self._exact[f"{scope_key}:{input_hash}"]
                return None
            return item.value

    def incr_loop(self, run_id: str, input_hash: str) -> int:
        key = f"{run_id}:{input_hash}"
        with self._lock:
            self._loops[key] += 1
            return self._loops[key]

    # --- vector -------------------------------------------------------------
    def index_call(self, scope_key: str, record: CallRecord) -> None:
        if not record.embedding:
            return
        # Mirror RedisStore: index side-effecting calls for duplicate detection
        # but don't retain their (never-reused) output.
        if record.cacheability == Cacheability.SIDE_EFFECTING and record.output is not None:
            record = record.model_copy(update={"output": None})
        with self._lock:
            self._calls[record.call_id] = (scope_key, record)

    def knn_search(self, scope_key: str, embedding: list[float], k: int = 3) -> list[Candidate]:
        with self._lock:
            calls = list(self._calls.values())
        scored: list[tuple[float, CallRecord]] = []
        for scope, rec in calls:
            if scope != scope_key or not rec.embedding:
                continue
            scored.append((cosine_similarity(embedding, rec.embedding), rec))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [
            Candidate(call_id=rec.call_id, cacheability=rec.cacheability.value,
                      similarity=sim, output=rec.output, normalized_input=rec.normalized_input)
            for sim, rec in scored[:k]
        ]

    # --- streams + runs -----------------------------------------------------
    def stream_key(self, run_id: str) -> str:
        return f"stream:redundant:events:{run_id}"

    def emit_event(self, event: RedundantEvent) -> str:
        with self._lock:
            self._seq += 1
            sid = f"{int(time.time()*1000)}-{self._seq}"
            self._streams[event.run_id].append((sid, event))
        return sid

    def read_events(self, run_id: str, after: str = "0", count: int = 1000) -> list[RedundantEvent]:
        with self._lock:
            rows = list(self._streams.get(run_id, []))
        out = []
        seen_after = after in ("0", "", None)
        for sid, ev in rows:
            if not seen_after:
                if sid == after:
                    seen_after = True
                continue
            ev.event_id = sid
            out.append(ev)
            if len(out) >= count:
                break
        return out

    def save_run(self, run: Run) -> None:
        with self._lock:
            self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> Optional[Run]:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self) -> list[Run]:
        with self._lock:
            return sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)
