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
} from "../types";

// Static fallback fixtures removed — dynamic data only.
// const FALLBACK_FIXES: SuggestedFix[] = [ ... ];
// function forceStatic(): boolean { ... }

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return (await res.json()) as T;
}

/** GET /findings — live data only. */
export async function getFindings(runId?: string): Promise<FindingsResponse> {
  // if (forceStatic()) {
  //   const fixture = await fetchJson<FindingsResponse>("/fixtures/findings.json");
  //   return { ...fixture, data_source: "static_fixture" };
  // }
  const qs = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  return await fetchJson<FindingsResponse>(`/findings${qs}`);
  // Removed static fixture fallback — dynamic data only.
  // try { ... } catch {
  //   const fixture = await fetchJson<FindingsResponse>("/fixtures/findings.json");
  //   return { ...fixture, data_source: "static_fixture" };
  // }
}

/** GET /api/runs — live data only. */
export async function listRuns(): Promise<Run[]> {
  // if (forceStatic()) return [];
  try {
    return await fetchJson<Run[]>("/api/runs");
  } catch {
    return [];
  }
}

/** POST /api/runs/{run_id}/rerun — live data only. */
export async function rerun(runId: string, _findings: FindingsResponse): Promise<RerunResponse> {
  // Removed static/offline projectRerun fallback — dynamic data only.
  const res = await fetch(`/api/runs/${encodeURIComponent(runId || "run-default")}/rerun`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`rerun → ${res.status}`);
  return (await res.json()) as RerunResponse;
}

/** GET /api/runs/{run_id}/report → RunReport. Returns null when unavailable. */
export async function getReport(runId: string): Promise<RunReport | null> {
  // Removed static synthReport fallback — dynamic data only.
  // if (forceStatic() || !runId) { return synthReport(runId); }
  if (!runId) return null;
  try {
    return await fetchJson<RunReport>(`/api/runs/${encodeURIComponent(runId)}/report`);
  } catch {
    return null;
  }
}

// function synthReport(runId: string): RunReport {
//   return {
//     run_id: runId || "run-default",
//     ...
//     fixes: FALLBACK_FIXES,  // static mock fixes — removed
//   };
// }

/** GET /alerts — Sentry incidents. Empty list on failure. */
export async function getAlerts(): Promise<AlertsResponse> {
  // if (forceStatic()) return { mock: true, events: [] };
  try {
    return await fetchJson<AlertsResponse>("/alerts");
  } catch {
    return { mock: false, events: [] };
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

// projectRerun (client-side offline projection) removed — dynamic data only.
