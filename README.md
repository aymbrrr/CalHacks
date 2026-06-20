# CalHacks

Runnable materials for the Redundant hackathon project.

## Run Redundant

No package install is required; the demo uses Python standard library only.

Run the scripted multi-agent demo and generate labelable data:

```bash
python3 -m redundant_app run-demo
```

Start the local dashboard/API:

```bash
python3 -m redundant_app serve --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

Dataset artifacts are written to:

```text
data/labelable-review-items.jsonl
data/terac-labels.jsonl
```

Check that data is being generated:

```bash
python3 -m redundant_app dataset-stats
```

Import `REDUNDANT_LABEL_DATA` from a real LLM turn:

```bash
python3 -m redundant_app ingest-label-data --file path/to/turn-output.md
```

Or paste through stdin:

```bash
pbpaste | python3 -m redundant_app ingest-label-data
```

Add a local label for one review item:

```bash
python3 -m redundant_app label-item --pair-id PAIR_ID --final-label safe_reuse --confidence 4 --reason "Same visible task and reusable answer."
```

Evaluate raw Redis reuse against the labels:

```bash
python3 -m redundant_app eval
```

Export unlabeled items for Terac:

```bash
python3 -m redundant_app export-terac
```

Run tests:

```bash
python3 -m unittest discover -s tests
```

## What Exists

- Runtime wrappers for LLM/tool calls.
- Exact and semantic cache decisions.
- Band-style multi-agent room messages.
- Redis Streams-style event log.
- Terac-style `CacheReuseReviewItem` JSONL generation.
- Pure LLM labelable turn generation.
- Import of pasted `REDUNDANT_LABEL_DATA` blocks from real use.
- Local annotation queue for tool-use and pure LLM items.
- Terac-shaped export and Redis-vs-label evaluation.
- Dataset health checks for pure LLM coverage.
- Dataset monitor events every few calls.
- Static dashboard for timeline, savings, duplicate clusters, fixes, and dataset preview.
- Replay-safe local data storage.

## API

- `POST /api/runs/start`
- `GET /api/runs/:run_id/events`
- `GET /api/runs/:run_id/stream`
- `GET /api/runs/:run_id/report`
- `POST /api/runs/:run_id/replay`
- `GET /api/dataset/stats`
- `GET /api/dataset/labelable`
- `POST /api/dataset/ingest`
- `GET /api/dataset/export.jsonl`
- `GET /api/dataset/terac-export`
- `GET /api/annotations/queue`
- `GET /api/annotations/labels`
- `POST /api/annotations/label`
- `GET /api/eval`

## Docs

- [Redundant implementation plan](docs/redundant-plan.md)
- [Terac readiness checklist](docs/terac-readiness.md)
- [Terac task design](docs/terac-task-design.md)
- [Labelable data query add-on](docs/labelable-data-query-addon.md)
- [Additional implementation context](docs/redundant-additional-context.md)
- [Original hackathon planning document](redundant_hackathon_plan.md)
