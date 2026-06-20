from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .demo import DEFAULT_TASK, run_demo
from .storage import JsonlStore


STATIC_DIR = Path(__file__).parent / "static"


class RedundantServer(BaseHTTPRequestHandler):
    store = JsonlStore()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            return self._send_file(STATIC_DIR / "index.html")
        if path.startswith("/static/"):
            return self._send_file(STATIC_DIR / path.removeprefix("/static/"))
        if path.startswith("/api/runs/") and path.endswith("/events"):
            run_id = path.split("/")[3]
            after = parse_qs(parsed.query).get("after", [None])[0]
            return self._json(self.store.list_events(run_id, after=after))
        if path.startswith("/api/runs/") and path.endswith("/stream"):
            run_id = path.split("/")[3]
            return self._sse(self.store.list_events(run_id))
        if path.startswith("/api/runs/") and path.endswith("/report"):
            run_id = path.split("/")[3]
            return self._json(self.store.get_report(run_id))
        if path == "/api/dataset/labelable":
            limit = parse_qs(parsed.query).get("limit", [None])[0]
            return self._json(self.store.list_label_items(limit=int(limit) if limit else None))
        if path == "/api/dataset/stats":
            return self._json(self.store.dataset_stats())
        if path == "/api/dataset/export.jsonl":
            return self._send_file(self.store.label_data_path, content_type="application/x-ndjson")
        self._json({"error": "not_found", "path": path}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/runs/start":
            body = self._body_json()
            report = run_demo(
                task=body.get("task") or DEFAULT_TASK,
                mode=body.get("mode") or "redundant",
                store=self.store,
            )
            return self._json({"run_id": report["run_id"], "status": "complete", "report": report})
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/replay"):
            body = self._body_json()
            report = run_demo(task=body.get("task") or DEFAULT_TASK, mode="replay", store=self.store)
            return self._json({"run_id": report["run_id"], "status": "complete", "report": report})
        self._json({"error": "not_found", "path": parsed.path}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _body_json(self) -> dict:
        length = int(self.headers.get("content-length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            return self._json({"error": "file_not_found"}, status=HTTPStatus.NOT_FOUND)
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", content_type or mimetypes.guess_type(path.name)[0] or "text/plain")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _sse(self, events: list[dict]) -> None:
        chunks = []
        for event in events:
            chunks.append(f"id: {event['event_id']}\nevent: redundant\ndata: {json.dumps(event, sort_keys=True)}\n\n")
        payload = "".join(chunks).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(host: str = "127.0.0.1", port: int = 8765, data_dir: str = "data") -> None:
    RedundantServer.store = JsonlStore(data_dir)
    server = ThreadingHTTPServer((host, port), RedundantServer)
    print(f"Redundant demo running at http://{host}:{port}")
    server.serve_forever()
