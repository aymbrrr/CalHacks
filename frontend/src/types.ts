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
