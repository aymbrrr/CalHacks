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
```

Check that data is being generated:

```bash
python3 -m redundant_app dataset-stats
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
- `GET /api/dataset/export.jsonl`

## Docs

- [Redundant implementation plan](docs/redundant-plan.md)
- [Terac readiness checklist](docs/terac-readiness.md)
- [Terac task design](docs/terac-task-design.md)
- [Labelable data query add-on](docs/labelable-data-query-addon.md)
- [Additional implementation context](docs/redundant-additional-context.md)
- [Original hackathon planning document](redundant_hackathon_plan.md)
