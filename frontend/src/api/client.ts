/** Thin wrapper over the FastAPI server.
 *
 *  Falls back to a checked-in fixture (`/fixtures/findings.json`) when the
 *  backend is unreachable or when the page is loaded with `?source=static`.
 *  This is the demo-safety path required by `docs/UI_REQUIREMENTS.md` UR-13.
 */
import type {
  AlertsResponse,
  FindingsResponse,
  RedundantEvent,
  RerunResponse,
  Run,
  RunReport,
  SuggestedFix,
} from "../types";

const FALLBACK_FIXES: SuggestedFix[] = [
  {
    fix_id: "cache-tool",
    title: "Cache pure tools",
    description: "Wrap repeated pure tool calls so identical inputs reuse results.",
    sponsor_hook: "Redis",
    code_hint: '@redundant.cached_tool(ttl="1h")\ndef web_search(q: str): ...',
  },
  {
    fix_id: "stable-prefix",
    title: "Stabilize prompt prefix",
    description: "Move timestamps/IDs out of the stable prompt prefix so Anthropic's prompt cache can hit.",
    sponsor_hook: "Anthropic",
    code_hint: "messages = [SYSTEM, TOOLS, *turn]  # stable prefix",
  },
  {
    fix_id: "compress-context",
    title: "Compress bloated context",
    description: "Compress large unsafe-to-reuse prompts before executing.",
    sponsor_hook: "Token Company",
    code_hint: "ctx = tokenco.compress(ctx, budget=2000)",
  },
  {
    fix_id: "embed-lookup",
    title: "Gate semantic reuse with the verifier",
    description: "Replace a repeated classification with a vector lookup, gated by Terac's verifier on held-out labels.",
    sponsor_hook: "Terac",
    code_hint: "if verifier.equivalent(a, b):\n    reuse(a)",
  },
];

const STATIC_PARAM = "source";
const STATIC_VALUE = "static";

function forceStatic(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get(STATIC_PARAM) === STATIC_VALUE;
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return (await res.json()) as T;
}

/** GET /findings, with static fixture fallback. */
export async function getFindings(runId?: string): Promise<FindingsResponse> {
  if (forceStatic()) {
    const fixture = await fetchJson<FindingsResponse>("/fixtures/findings.json");
    return { ...fixture, data_source: "static_fixture" };
  }
  try {
    const qs = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return await fetchJson<FindingsResponse>(`/findings${qs}`);
  } catch {
    // Backend down — fall through to the demo-safe fixture.
    const fixture = await fetchJson<FindingsResponse>("/fixtures/findings.json");
    return { ...fixture, data_source: "static_fixture" };
  }
}

/** GET /api/runs, empty array on failure (lets the selector render). */
export async function listRuns(): Promise<Run[]> {
  if (forceStatic()) return [];
  try {
    return await fetchJson<Run[]>("/api/runs");
  } catch {
    return [];
  }
}

/** POST /api/runs/{run_id}/rerun. Falls back to a client-side projection from
 *  the already-loaded findings so the cost-drop beat still works offline. */
export async function rerun(runId: string, findings: FindingsResponse): Promise<RerunResponse> {
  if (!forceStatic()) {
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(runId || "run-default")}/rerun`, {
        method: "POST",
      });
      if (res.ok) return (await res.json()) as RerunResponse;
    } catch {
      // fall through
    }
  }
  return projectRerun(runId, findings);
}

/** GET /api/runs/{run_id}/report → RunReport (fixes + clusters). Falls back to
 *  a small static fix list so the panel stays populated when offline. */
export async function getReport(runId: string): Promise<RunReport | null> {
  if (forceStatic() || !runId) {
    return synthReport(runId);
  }
  try {
    return await fetchJson<RunReport>(`/api/runs/${encodeURIComponent(runId)}/report`);
  } catch {
    return synthReport(runId);
  }
}

function synthReport(runId: string): RunReport {
  return {
    run_id: runId || "run-default",
    attempted_calls: 0,
    executed_calls: 0,
    reused_or_blocked_calls: 0,
    redundant_rate: 0,
    estimated_baseline_cost_usd: 0,
    actual_cost_usd: 0,
    saved_cost_usd: 0,
    saved_latency_ms: 0,
    saved_tokens: 0,
    worst_duplicate_cluster: null,
    clusters: [],
    fixes: FALLBACK_FIXES,
  };
}

/** GET /alerts — Sentry incidents (mock when no DSN). Empty list on failure. */
export async function getAlerts(): Promise<AlertsResponse> {
  if (forceStatic()) return { mock: true, events: [] };
  try {
    return await fetchJson<AlertsResponse>("/alerts");
  } catch {
    return { mock: true, events: [] };
  }
}

/** POST /api/runs/start → Run. Kicks off a new run on the backend. */
export async function startRun(task: string, mode = "band"): Promise<Run> {
  const res = await fetch("/api/runs/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, mode }),
  });
  if (!res.ok) throw new Error(`startRun → ${res.status}`);
  return res.json() as Promise<Run>;
}

/**
 * Subscribe to GET /api/runs/{run_id}/stream (SSE).
 * Calls onEvent for each RedundantEvent, onDone when the run completes.
 * Returns a cleanup function that closes the EventSource.
 */
export function streamRun(
  runId: string,
  onEvent: (ev: RedundantEvent) => void,
  onDone: (run: Run) => void
): () => void {
  const es = new EventSource(`/api/runs/${encodeURIComponent(runId)}/stream`);
  es.addEventListener("redundant", (e) => {
    try {
      onEvent(JSON.parse((e as MessageEvent).data) as RedundantEvent);
    } catch {
      /* skip malformed event */
    }
  });
  es.addEventListener("done", (e) => {
    try {
      onDone(JSON.parse((e as MessageEvent).data) as Run);
    } catch {
      /* skip */
    }
    es.close();
  });
  es.onerror = () => es.close();
  return () => es.close();
}

function projectRerun(runId: string, data: FindingsResponse): RerunResponse {
  const cacheHits: RerunResponse["cache_hits"] = [];
  let saved = 0;
  for (const f of data.findings) {
    if (f.route !== "cache") continue;
    saved += f.dollar_cost;
    cacheHits.push({
      finding_id: f.finding_id,
      tool: f.description.split(" ", 1)[0] || f.type,
      served_from_cache: true,
      saved: Number(f.dollar_cost.toFixed(6)),
    });
  }
  return {
    run_id: runId || "run-default",
    original_cost: Number(data.total_cost_usd.toFixed(6)),
    cached_cost: Number((data.total_cost_usd - saved).toFixed(6)),
    saved: Number(saved.toFixed(6)),
    cache_hits: cacheHits,
  };
}
