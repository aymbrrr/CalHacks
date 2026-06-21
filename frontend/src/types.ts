/** Backend types mirrored from `backend/redundant/span_schema.py` and
 *  `backend/redundant/schema.py`. Field names and casing match the Pydantic
 *  models verbatim so JSON round-trips with no translation layer.
 */

export interface TokenCost {
  input: number;
  output: number;
}

export interface Span {
  span_id: string;
  parent_span_id: string | null;
  kind: "agent" | "llm" | "tool";
  name: string;
  tool_name: string | null;
  agent_name: string;
  input: string;
  output: string;
  input_hash: string;
  start_time: number; // epoch ms
  end_time: number;
  tokens: TokenCost;
  model: string | null;
  cost_usd: number;
}

export interface Evidence {
  similarity?: number | null;
  cycle_path?: string[] | null;
  convergence: "none" | "partial" | "converged" | "unknown";
}

export type FindingType = "repetition" | "cycle" | "semantic_duplicate";
export type FindingRoute = "cache" | "alert";
export type FindingSeverity = "wasteful" | "runaway";

export interface Finding {
  finding_id: string;
  type: FindingType;
  span_ids: string[];
  representative_span_id: string;
  count: number;
  description: string;
  token_cost: TokenCost;
  dollar_cost: number;
  severity: FindingSeverity;
  route: FindingRoute;
  cacheable: boolean;
  evidence: Evidence;
  alert_fired: boolean;
  models_involved: string[];
}

/** Response shape of `GET /findings`. */
export interface FindingsResponse {
  spans: Span[];
  findings: Finding[];
  total_cost_usd: number;
  wasted_cost_usd: number;
  waste_pct: number;
  cost_by_model: Record<string, number>;
  cache_entries_written: number;
  alerts_fired: number;
  span_count: number;
  event_count?: number;
  data_source?: "live" | "event_stream" | "live_pending" | "json" | "demo_fixture" | "static_fixture" | string;
}

export interface Run {
  run_id: string;
  task: string;
  mode: "baseline" | "redundant" | "replay" | string;
  status: "idle" | "running" | "complete" | "failed" | string;
  started_at: string;
  completed_at?: string | null;
  error?: string | null;
}

export interface SuggestedFix {
  fix_id: string;
  title: string;
  description: string;
  sponsor_hook?: string | null;
  code_hint?: string | null;
}

export interface DuplicateCluster {
  cluster_id: string;
  label: string;
  calls: number;
  unique_needed: number;
  waste_percent: number;
  saved_cost_usd: number;
  saved_latency_ms: number;
  agent_ids: string[];
}

export interface RunReport {
  run_id: string;
  attempted_calls: number;
  executed_calls: number;
  reused_or_blocked_calls: number;
  redundant_rate: number;
  estimated_baseline_cost_usd: number;
  actual_cost_usd: number;
  saved_cost_usd: number;
  saved_latency_ms: number;
  saved_tokens: number;
  worst_duplicate_cluster?: string | null;
  clusters: DuplicateCluster[];
  fixes: SuggestedFix[];
}

/** Response shape of `GET /alerts`. */
export interface AlertEvent {
  finding_id?: string;
  type?: string;
  level?: string;
  message?: string;
  run_id?: string;
  ts?: string | number;
  [key: string]: unknown;
}

export interface AlertsResponse {
  mock: boolean;
  events: AlertEvent[];
}

/** Response shape of `POST /api/runs/{run_id}/rerun`. */
export interface RerunCacheHit {
  finding_id: string;
  tool: string;
  served_from_cache: boolean;
  saved: number;
}

export interface RerunResponse {
  run_id: string;
  original_cost: number;
  cached_cost: number;
  saved: number;
  cache_hits: RerunCacheHit[];
}

export interface RedundantEvent {
  event_id: string;
  run_id: string;
  ts: string;
  agent_id: string;
  call_id: string;
  call_type: "llm" | "tool";
  tool_name: string;
  decision: string;
  cacheability: string;
  summary: string;
  explanation: string;
  saved_cost_usd: number;
  saved_latency_ms: number;
  saved_tokens: number;
  actual_cost_usd: number;
  source_call_id?: string | null;
  verifier_score?: number | null;
  cluster_id?: string | null;
  sponsor_hooks: string[];
}
