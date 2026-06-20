# Claude Code Hook Demo: Oneshot / Experimental

This folder is a clearly separated demo scaffold for trying Redundant with Claude Code hooks.

It was oneshotted during hackathon prep and may be unreliable. Treat it as a demo artifact, not production architecture. It is useful for showing the idea that Redundant can sit near a coding agent, capture visible submitted prompts and summarized tool calls, and turn repeated work into labelable review data.

## What It Demonstrates

- Claude Code `UserPromptSubmit` hooks can capture visible submitted prompts.
- Claude Code `PreToolUse` / `PostToolUse` hooks can capture summarized tool metadata.
- Redundant can turn near-repeated prompt/tool calls into `CacheReuseReviewItem` data.
- The generated items flow into the existing local dataset and dashboard.

## What It Does Not Guarantee

- It does not capture hidden system, developer, or model-internal context.
- It does not safely block or rewrite prompts.
- It may miss events if Claude Code hook schemas change.
- It may over-label or under-label repeated work because the similarity logic is intentionally simple.
- It should not be used on private repositories or sensitive prompts without reviewing the captured JSONL files.

## Files In This Demo

- `settings.redundant.example.json`: example Claude Code hook config.
- `sample-user-prompt-1.json`: dry-run input that simulates a first Claude prompt.
- `sample-user-prompt-2.json`: dry-run input that simulates a similar later Claude prompt.

Supporting code lives in the app so it can reuse Redundant storage, validation, and dataset stats:

- `redundant_app/claude_hooks.py`
- `redundant_app/session_bridge.py`
- `redundant_app/cache.py`

## Setup

From the repo root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Install Claude Code separately, then verify:

```bash
claude --version
claude doctor
```

Copy the example config into the local Claude settings path:

```bash
mkdir -p .claude
cp oneshot_demos/claude-code-hook-demo/settings.redundant.example.json .claude/settings.local.json
```

The local settings file is gitignored.

## Dry Run Without Claude Code

This proves the hook command can capture two similar prompts and generate one labelable item.

```bash
tmpdir="$(mktemp -d /tmp/redundant-claude-hook.XXXXXX)"
.venv/bin/python -m redundant_app claude-hook --data-dir "$tmpdir" < oneshot_demos/claude-code-hook-demo/sample-user-prompt-1.json
.venv/bin/python -m redundant_app claude-hook --data-dir "$tmpdir" --context < oneshot_demos/claude-code-hook-demo/sample-user-prompt-2.json
.venv/bin/python -m redundant_app dataset-stats --data-dir "$tmpdir"
```

Expected result: one pure LLM labelable item.

## Live Claude Code Demo

1. Start Redundant:

   ```bash
   .venv/bin/python -m redundant_app serve --port 8765
   ```

2. Open `http://127.0.0.1:8765`.
3. Run Claude Code from this repo:

   ```bash
   claude
   ```

4. Submit two similar prompts:

   ```text
   Plan the Redundant LangCache demo for Claude Code.
   Plan a Redundant LangCache demo for Claude Code hooks.
   ```

5. Refresh the dashboard and check dataset stats:

   ```bash
   .venv/bin/python -m redundant_app dataset-stats
   ```

Captured local artifacts are ignored under `data/`:

- `data/claude-code-hook-events.jsonl`
- `data/claude-code-captured-calls.jsonl`
- `data/labelable-review-items.jsonl`
