# CalHacks

Runnable materials for the Redundant hackathon project.

## Run Redundant

Install dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

The app runs offline with a deterministic LangCache-compatible local backend. To use managed Redis LangCache instead, set:

```bash
export LANGCACHE_SERVER_URL="https://..."
export LANGCACHE_CACHE_ID="..."
export LANGCACHE_API_KEY="..."
```

Set `REDUNDANT_CACHE_BACKEND=local` to force the offline backend.

Run the scripted multi-agent demo and generate labelable data:

```bash
.venv/bin/python -m redundant_app run-demo
```

Start the local dashboard/API:

```bash
.venv/bin/python -m redundant_app serve --port 8765
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
.venv/bin/python -m redundant_app dataset-stats
```

Import `REDUNDANT_LABEL_DATA` from a real LLM turn:

```bash
.venv/bin/python -m redundant_app ingest-label-data --file path/to/turn-output.md
```

Or paste through stdin:

```bash
pbpaste | .venv/bin/python -m redundant_app ingest-label-data
```

For the always-on local workflow, paste or append final `REDUNDANT_LABEL_DATA` sections into:

```text
data/redundant-label-inbox.md
```

Then import and archive the inbox:

```bash
.venv/bin/python -m redundant_app ingest-inbox
```

Or leave the coding-session bridge running while you work:

```bash
.venv/bin/python -m redundant_app watch-sessions --interval 20
```

The bridge polls `data/redundant-label-inbox.md`, imports any visible `REDUNDANT_LABEL_DATA` sections, archives accepted inbox text, and prints total/pure-LLM/labeled/unlabeled counts. It does not intercept hidden Codex internals; it only observes the visible label blocks emitted at session boundaries.

## Claude Code Hook Demo

This repo includes a local Claude Code hook demo that captures visible submitted prompts and summarized tool calls into Redundant.

Ready-to-use local config:

```text
.claude/settings.local.json
```

Shareable oneshot demo folder:

```text
oneshot_demos/claude-code-hook-demo/
```

Copy the example config from that folder when you want to try it:

```bash
mkdir -p .claude
cp oneshot_demos/claude-code-hook-demo/settings.redundant.example.json .claude/settings.local.json
```

When Claude Code runs in this repo, the hooks call:

```bash
.venv/bin/python -m redundant_app claude-hook --data-dir data
```

Captured artifacts stay local and ignored:

```text
data/claude-code-hook-events.jsonl
data/claude-code-captured-calls.jsonl
data/labelable-review-items.jsonl
```

Demo script:

1. Start the Redundant dashboard:

   ```bash
   .venv/bin/python -m redundant_app serve --port 8765
   ```

2. In a second terminal, run Claude Code from this repo.
3. Submit two similar prompts, such as:

   ```text
   Plan the Redundant LangCache demo for Claude Code.
   Plan a Redundant LangCache demo for Claude Code hooks.
   ```

4. Ask Claude Code to perform a repeated repo read or search.
5. Refresh the dashboard and show the labelable item count increasing.
6. Run:

   ```bash
   .venv/bin/python -m redundant_app dataset-stats
   ```

The hook uses Claude Code lifecycle events. It can capture visible submitted prompts and tool metadata, but it does not capture hidden system/developer prompts.

This Claude Code hook path is a whole oneshotted demo and may be unreliable. Read [the demo README](oneshot_demos/claude-code-hook-demo/README.md) before showing it to teammates.

Add a local label for one review item:

```bash
.venv/bin/python -m redundant_app label-item --pair-id PAIR_ID --final-label safe_reuse --confidence 4 --reason "Same visible task and reusable answer."
```

Evaluate raw Redis reuse against the labels:

```bash
.venv/bin/python -m redundant_app eval
```

Export unlabeled items for Terac:

```bash
.venv/bin/python -m redundant_app export-terac
```

Run tests:

```bash
.venv/bin/python -m unittest discover -s tests
```

## What Exists

- Runtime wrappers for LLM/tool calls.
- Redis LangCache exact and semantic cache decisions, with local fallback.
- Band-style multi-agent room messages.
- Redis Streams-style event log.
- Terac-style `CacheReuseReviewItem` JSONL generation.
- Pure LLM labelable turn generation.
- Import of pasted `REDUNDANT_LABEL_DATA` blocks from real use.
- Always-on local inbox import for real chat turns.
- Coding-session bridge that watches the local inbox and reports whether data is accumulating.
- Claude Code hook capture for submitted prompts and summarized tool calls.
- Clearly isolated oneshot Claude Code demo under `oneshot_demos/claude-code-hook-demo/`.
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
