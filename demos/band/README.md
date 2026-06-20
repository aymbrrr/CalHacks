# Band Multi-Agent Redundant Demo

## Real Band Mode (live agents)

1. Copy credentials into `agent_config.yaml` at the repo root (see `agent_config.example.yaml`).
2. Run:
   ```bash
   python demos/band/run_real_band_agents.py
   ```
3. Go to the Band chat room where the four remote agents are members and send:
   ```
   @ResearchAgent Research agent cost optimization tools, compare Redis/Sentry-style approaches, and produce a short recommendation.
   ```
4. Agent replies appear in Band chat; the Redundant trace is written to `demos/band/traces/band_demo_real_band_trace.json`.

This is Dev 2's deterministic Band-facing workflow for the Redundant demo. It uses a local `FallbackBandRoom` so the flow works without live Band credentials, while keeping the Band room transcript, agent names, wrapper payload shapes, trace spans, decision events, and replay path stable.

## Commands

```bash
python demos/band/run_band_demo.py --mode baseline --run-id run-001
python demos/band/run_band_demo.py --mode redundant --run-id run-001
python demos/band/replay_trace.py demos/band/traces/band_demo_trace.json --run-id run-001
```

Use dry-run replay when Redis is not running:

```bash
python demos/band/replay_trace.py demos/band/traces/band_demo_trace.json --run-id run-001 --dry-run
```

## Agents

- `ResearchAgent`: plans the research, searches docs, scans wrapper patterns, summarizes the shared source, and posts findings.
- `ReportAgent`: reads Band context, repeats overlapping calls, accepts safe reuse, blocks unsafe semantic reuse, and writes the final recommendation.
- `AuditAgent`: deliberately repeats the canonical search query so the exact duplicate cluster spans three distinct agents.
- `VerifierAgent`: calls `verify_source` 12 times with unchanged uncertainty to trigger `RUNAWAY_LOOP_ALERT`.

## Expected Moments

- Terminal and transcript include: `ReportAgent reused ResearchAgent's prior result.`
- Exact cluster: `ResearchAgent`, `ReportAgent`, and `AuditAgent` all call `search_docs("agent cost optimization redis sentry")`.
- Semantic reuse: `ReportAgent.scan_repo("tool cache decorator")` reuses `ResearchAgent.scan_repo("cached tool wrapper")`.
- Summary reuse: both research and report summarize `https://redundant.dev/examples/agent-cost-caching`.
- Unsafe semantic block: Redis cache invalidation docs are rejected for the Sentry alert routing query.
- Runaway alert: `VerifierAgent.verify_source(...)` runs 12 times and emits `RUNAWAY_LOOP_ALERT`.

## Trace Files

- Redundant-enabled frozen trace: `demos/band/traces/band_demo_trace.json`
- Baseline trace: `demos/band/traces/band_demo_baseline_trace.json`

Each trace contains the run metadata, agent prompts, Band transcript, raw spans, decision events, duplicate clusters, final cost report, replay command, and fallback limitations.

## Fallback Limitations

- This uses a local Band room adapter instead of a live Band room.
- LLM and tool outputs are scripted so the demo is deterministic.
- The runtime is a Dev 2 shim that exposes the requested `redundant.llm()` and `redundant.tool()` payload shapes; swap this with Dev 1's backend when available.
- Redis replay works with `redis-py` and `REDIS_URL`; otherwise `--dry-run` prints the equivalent `XADD` payloads.
