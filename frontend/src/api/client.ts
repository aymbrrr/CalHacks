/** Thin wrapper over the FastAPI server.
 *
 *  Falls back to a checked-in fixture (`/fixtures/findings.json`) when the
 *  backend is unreachable or when the page is loaded with `?source=static`.
 *  This is the demo-safety path required by `docs/UI_REQUIREMENTS.md` UR-13.
 */
import type { FindingsResponse, Run } from "../types";

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
  if (forceStatic()) return fetchJson<FindingsResponse>("/fixtures/findings.json");
  try {
    const qs = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return await fetchJson<FindingsResponse>(`/findings${qs}`);
  } catch {
    // Backend down — fall through to the demo-safe fixture.
    return fetchJson<FindingsResponse>("/fixtures/findings.json");
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
