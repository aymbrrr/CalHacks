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
        # Pin RESP2: redis-py 8.x talking to Redis 8 may negotiate RESP3, whose
        # FT.SEARCH reply format the search-result parser mishandles — KNN then
        # returns zero docs even though the index matches. RESP2 parses correctly.
        self.r = client or redis.from_url(settings.redis_url, decode_responses=False, protocol=2)
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

    def _index_meta_key(self) -> str:
        return f"{self.ns}:index:meta"

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
        key = self._exact_key(scope_key, input_hash)
        raw = self.r.get(key)
        if not raw:
            print(f"[redis_store] GET_EXACT MISS  key={key!r}")
            return None
        record = CallRecord.model_validate_json(raw)
        print(f"[redis_store] GET_EXACT HIT   key={key!r}  source_call_id={record.call_id!r}")
        return record

    def incr_loop(self, run_id: str, input_hash: str) -> int:
        key = self._loop_key(run_id, input_hash)
        count = self.r.incr(key)
        if count == 1:
            self.r.expire(key, 3600)
        return int(count)

    # --- Step 5: vector index ----------------------------------------------
    def ensure_index(self) -> None:
        """Create the RediSearch vector index, reconciling a stale one.

        The vector field's DIM (and the key prefix/namespace) are baked into the
        index at creation. If any of those drift — e.g. ``embedding_dim`` changes,
        or an old index was created by a previous schema — an existing index is
        silently wrong and KNN returns nothing. We stamp a small meta key with the
        schema signature and drop+recreate when it no longer matches, so changing
        the embedding model never leaves a quietly broken index behind.
        """
        from redis.commands.search.field import TagField, VectorField, TextField
        from redis.commands.search.index_definition import IndexDefinition, IndexType

        prefix = f"{self.ns}:call:"
        signature = f"{self.s.embedding_dim}:COSINE:{prefix}"
        meta_key = self._index_meta_key()

        try:
            self.r.ft(self.index_name).info()
            exists = True
        except redis.ResponseError:
            exists = False

        if exists:
            have = self.r.get(meta_key)
            have = have.decode() if isinstance(have, bytes) else have
            if have == signature:
                return  # already present and matches the current schema
            # Drift (or an unstamped legacy index): drop and recreate. Keep the
            # underlying documents — matching-dim docs get reindexed automatically.
            try:
                self.r.ft(self.index_name).dropindex(delete_documents=False)
            except Exception:
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
        definition = IndexDefinition(prefix=[prefix], index_type=IndexType.HASH)
        self.r.ft(self.index_name).create_index(schema, definition=definition)
        self.r.set(meta_key, signature)

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
            .return_fields("call_id", "cacheability", "output", "normalized_input",
                           "cost_usd", "latency_ms", "input_tokens", "output_tokens", "dist")
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
                    cost_usd=_to_float(getattr(doc, "cost_usd", 0.0)),
                    latency_ms=_to_int(getattr(doc, "latency_ms", 0)),
                    input_tokens=_to_int(getattr(doc, "input_tokens", 0)),
                    output_tokens=_to_int(getattr(doc, "output_tokens", 0)),
                )
            )
        return out

    # --- Step 8: streams + run metadata ------------------------------------
    def emit_event(self, event: RedundantEvent) -> str:
        """XADD one event; backfills event_id with the stream ID. Returns the ID."""
        key = self.stream_key(event.run_id)
        sid = self.r.xadd(key, {"payload": event.model_dump_json()})
        sid_str = sid.decode() if isinstance(sid, bytes) else str(sid)
        print(
            f"[redis_store] XADD  stream={key!r}  sid={sid_str!r}"
            f"  decision={event.decision.value!r}  tool={event.tool_name!r}"
        )
        return sid_str

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

    def list_runs(self) -> list[Run]:
        """Scan run keys and return all known Runs, newest first.

        SCAN over a tiny namespace (one entry per run); fine at hackathon scale.
        For larger deployments, swap to a sorted-set index keyed by started_at.
        """
        runs: list[Run] = []
        pattern = f"{self.ns}:run:*"
        for key in self.r.scan_iter(match=pattern):
            raw = self.r.get(key)
            if raw:
                try:
                    runs.append(Run.model_validate_json(raw))
                except Exception:
                    continue
        runs.sort(key=lambda r: r.started_at, reverse=True)
        return runs


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


def _to_float(v: Any) -> float:
    try:
        return float(_dec(v))
    except (TypeError, ValueError):
        return 0.0


def _to_int(v: Any) -> int:
    try:
        return int(float(_dec(v)))
    except (TypeError, ValueError):
        return 0
