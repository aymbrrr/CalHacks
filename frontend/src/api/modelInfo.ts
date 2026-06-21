/** Client-side mirror of `backend/redundant/pricing.py`.
 *
 *  Shared so chips and tooltips render with the same provider/family labels
 *  whether the response came from `/findings` or a static fixture. Drift is
 *  the bug to watch — keep this aligned with the backend registry when adding
 *  new models.
 */

export type Provider =
  | "anthropic"
  | "openai"
  | "google"
  | "mistral"
  | "local"
  | "unknown";

export type Family =
  | "claude"
  | "gpt"
  | "gemini"
  | "mistral"
  | "llama"
  | "qwen"
  | "embedding"
  | "unknown";

export interface ModelInfo {
  provider: Provider;
  family: Family;
  shortLabel: string;
}

const REGISTRY: Record<string, ModelInfo> = {
  "claude-opus-4-8":      { provider: "anthropic", family: "claude",    shortLabel: "Opus 4.8" },
  "claude-opus-4-7":      { provider: "anthropic", family: "claude",    shortLabel: "Opus 4.7" },
  "claude-sonnet-4-6":    { provider: "anthropic", family: "claude",    shortLabel: "Sonnet 4.6" },
  "claude-haiku-4-5":     { provider: "anthropic", family: "claude",    shortLabel: "Haiku 4.5" },
  "gpt-4o":               { provider: "openai",    family: "gpt",       shortLabel: "GPT-4o" },
  "gpt-4o-mini":          { provider: "openai",    family: "gpt",       shortLabel: "GPT-4o mini" },
  "gemini-1.5-pro":       { provider: "google",    family: "gemini",    shortLabel: "Gemini 1.5 Pro" },
  "gemini-1.5-flash":     { provider: "google",    family: "gemini",    shortLabel: "Gemini 1.5 Flash" },
  "mistral-large":        { provider: "mistral",   family: "mistral",   shortLabel: "Mistral Large" },
  "llama-3.1-70b":        { provider: "local",     family: "llama",     shortLabel: "Llama 3.1 70B" },
  "qwen-2.5-72b":         { provider: "local",     family: "qwen",      shortLabel: "Qwen 2.5 72B" },
  "text-embedding-3-small":{provider: "openai",    family: "embedding", shortLabel: "Embedding 3 small" },
};

const DEFAULT: ModelInfo = { provider: "unknown", family: "unknown", shortLabel: "model" };

export function modelInfo(model: string | null | undefined): ModelInfo {
  if (!model) return DEFAULT;
  if (REGISTRY[model]) return REGISTRY[model];

  // Prefix match — handles dated variants like gpt-4o-2025-08-01.
  for (const key of Object.keys(REGISTRY)) {
    if (model.startsWith(key) || key.startsWith(model)) return REGISTRY[key];
  }

  // Heuristic provider sniff so unknown future model strings still pick up
  // the right sponsor cues in the UI.
  const lo = model.toLowerCase();
  if (lo.startsWith("claude"))  return { provider: "anthropic", family: "claude", shortLabel: shortenLabel(model) };
  if (lo.startsWith("gpt"))     return { provider: "openai",    family: "gpt",    shortLabel: shortenLabel(model) };
  if (lo.startsWith("gemini"))  return { provider: "google",    family: "gemini", shortLabel: shortenLabel(model) };
  if (/llama|qwen|mistral/.test(lo)) {
    const family: Family = lo.includes("mistral") ? "mistral" : lo.includes("qwen") ? "qwen" : "llama";
    return { provider: "local", family, shortLabel: shortenLabel(model) };
  }

  return { ...DEFAULT, shortLabel: shortenLabel(model) };
}

/** Trim Hugging-Face-style `org/Model-Name` paths down to the trailing slug. */
function shortenLabel(model: string): string {
  return model.includes("/") ? model.split("/").pop()! : model;
}

/** Convenience: just the label. */
export function shortLabel(model: string | null | undefined): string {
  if (!model) return "—";
  return modelInfo(model).shortLabel;
}

/** Sponsor chip color for a provider — keys on theme.ts sponsor palette. */
export function providerSponsor(provider: Provider): "anthropic" | "redis" | "tokenco" | "terac" | null {
  switch (provider) {
    case "anthropic":
      return "anthropic";
    default:
      return null;
  }
}
