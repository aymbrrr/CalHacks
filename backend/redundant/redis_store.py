"""Redis layer: exact cache, vector (RediSearch) index, and Redis Streams.

The UI never touches Redis directly; it consumes the HTTP /events or /stream
endpoints (Chunk 9). This module is the single owner of all Redis keys.

Key layout (namespace defaults to "redundant"):
  - Exact cache:   {ns}:cache:exact:{scope_key}:{input_hash}   (string, TTL'd)
  - Loop counter:  {ns}:loop:{run_id}:{input_hash}              (int, run-lived)
  - Vector docs:   {ns}:call:{call_id}                          (HASH, indexed)
  - Vector index:  idx:{ns}:calls                               (RediSearch)
  - Event stream:  stream:redundant:events:{run_id}             (XADD)
  - Run metadata:  {ns}:run:{run_id}                            (string JSON)
"""

from __future__ import annotations

import json
import struct
from typing import Any, Optional

import redis

from redundant.config import SETTINGS, Settings, ttl_for
from redundant.schema import Cacheability, CallRecord, RedundantEvent, Run
from redundant.verifier import Candidate


def _f32_bytes(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


class RedisStore:
    def __init__(self, settings: Settings = SETTINGS, client: redis.Redis | None = None):
        self.s = settings
        self.ns = settings.namespace
        self.r = client or redis.from_url(settings.redis_url, decode_responses=False)
        self.index_name = f"idx:{self.ns}:calls"

    # --- connectivity -------------------------------------------------------
    def ping(self) -> bool:
        return bool(self.r.ping())

    # --- keys ---------------------------------------------------------------
    def _exact_key(self, scope_key: str, input_hash: str) -> str:
        return f"{self.ns}:cache:exact:{scope_key}:{input_hash}"

    def _loop_key(self, run_id: str, input_hash: str) -> str:
        return f"{self.ns}:loop:{run_id}:{input_hash}"

    def _call_key(self, call_id: str) -> str:
        return f"{self.ns}:call:{call_id}"

    def _run_key(self, run_id: str) -> str:
        return f"{self.ns}:run:{run_id}"

    def stream_key(self, run_id: str) -> str:
        return f"stream:redundant:events:{run_id}"

    # --- Step 4: exact cache ------------------------------------------------
    def put_exact(self, scope_key: str, record: CallRecord) -> None:
        ttl = ttl_for(record.cacheability.value, self.s)
        if ttl is None:  # side_effecting: never stored for reuse
            return
        key = self._exact_key(scope_key, record.input_hash)
        self.r.set(key, record.model_dump_json(), ex=ttl)

    def get_exact(self, scope_key: str, input_hash: str) -> Optional[CallRecord]:
        raw = self.r.get(self._exact_key(scope_key, input_hash))
        if not raw:
            return None
        return CallRecord.model_validate_json(raw)

    def incr_loop(self, run_id: str, input_hash: str) -> int:
        key = self._loop_key(run_id, input_hash)
        count = self.r.incr(key)
        if count == 1:
            self.r.expire(key, 3600)
        return int(count)

    # --- Step 5: vector index ----------------------------------------------
    def ensure_index(self) -> None:
        """Create the RediSearch vector index if it does not exist."""
        from redis.commands.search.field import TagField, VectorField, TextField
        from redis.commands.search.index_definition import IndexDefinition, IndexType

        try:
            self.r.ft(self.index_name).info()
            return  # already exists
        except redis.ResponseError:
            pass

        schema = (
            TagField("run_id"),
            TagField("scope_key"),
            TagField("tool_name"),
            TagField("cacheability"),
            TextField("output"),
            VectorField(
                "embedding",
                "HNSW",
                {
                    "TYPE": "FLOAT32",
                    "DIM": self.s.embedding_dim,
                    "DISTANCE_METRIC": "COSINE",
                },
            ),
        )
        definition = IndexDefinition(prefix=[f"{self.ns}:call:"], index_type=IndexType.HASH)
        self.r.ft(self.index_name).create_index(schema, definition=definition)

    def index_call(self, scope_key: str, record: CallRecord) -> None:
        if not record.embedding:
            return
        # Side-effecting calls are indexed only so duplicate side-effects can be
        # detected by vector match; their output is never reused, so don't persist
        # it (avoids retaining write-action payloads in the index).
        output = "" if record.cacheability == Cacheability.SIDE_EFFECTING else (record.output or "")
        self.r.hset(
            self._call_key(record.call_id),
            mapping={
                "run_id": record.run_id,
                "scope_key": scope_key,
                "tool_name": record.tool_name,
                "cacheability": record.cacheability.value,
                "output": output.encode("utf-8"),
                "call_id": record.call_id,
                "normalized_input": record.normalized_input.encode("utf-8"),
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "cost_usd": str(record.cost_usd),
                "latency_ms": record.latency_ms,
                "embedding": _f32_bytes(record.embedding),
            },
        )

    def knn_search(
        self, scope_key: str, embedding: list[float], k: int = 3
    ) -> list[Candidate]:
        """Return nearest prior calls within the same scope, best-first."""
        from redis.commands.search.query import Query

        q = (
            Query(f"(@scope_key:{{{_escape_tag(scope_key)}}})=>[KNN {k} @embedding $vec AS dist]")
            .sort_by("dist")
            .return_fields("call_id", "cacheability", "output", "normalized_input", "dist")
            .dialect(2)
        )
        res = self.r.ft(self.index_name).search(q, query_params={"vec": _f32_bytes(embedding)})
        out: list[Candidate] = []
        for doc in res.docs:
            dist = float(getattr(doc, "dist", 1.0))
            out.append(
                Candidate(
                    call_id=_dec(getattr(doc, "call_id", "")),
                    cacheability=_dec(getattr(doc, "cacheability", "pure")),
                    similarity=max(0.0, 1.0 - dist),  # cosine distance -> similarity
                    output=_dec(getattr(doc, "output", "")),
                    normalized_input=_dec(getattr(doc, "normalized_input", "")),
                )
            )
        return out

    # --- Step 8: streams + run metadata ------------------------------------
    def emit_event(self, event: RedundantEvent) -> str:
        """XADD one event; backfills event_id with the stream ID. Returns the ID."""
        sid = self.r.xadd(self.stream_key(event.run_id), {"payload": event.model_dump_json()})
        return sid.decode() if isinstance(sid, bytes) else str(sid)

    def read_events(self, run_id: str, after: str = "0", count: int = 1000) -> list[RedundantEvent]:
        start = "-" if after in ("0", "", None) else f"({after}"
        rows = self.r.xrange(self.stream_key(run_id), min=start, max="+", count=count)
        events: list[RedundantEvent] = []
        for sid, fields in rows:
            payload = fields.get(b"payload") or fields.get("payload")
            if payload is None:
                continue
            ev = RedundantEvent.model_validate_json(payload)
            ev.event_id = sid.decode() if isinstance(sid, bytes) else str(sid)
            events.append(ev)
        return events

    def save_run(self, run: Run) -> None:
        self.r.set(self._run_key(run.run_id), run.model_dump_json())

    def get_run(self, run_id: str) -> Optional[Run]:
        raw = self.r.get(self._run_key(run_id))
        return Run.model_validate_json(raw) if raw else None


def _escape_tag(value: str) -> str:
    # RediSearch tag values must escape these special characters.
    out = []
    for ch in value:
        if ch in {":", "-", " ", ".", "/", "{", "}", "|", "@", "(", ")"}:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _dec(v: Any) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return "" if v is None else str(v)
