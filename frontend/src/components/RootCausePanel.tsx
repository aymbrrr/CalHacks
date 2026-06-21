import { hexA, theme } from "../theme";
import { formatDemoUsd } from "../api/displayMoney";
import { shortLabel } from "../api/modelInfo";
import type { Finding } from "../types";

interface Props {
  finding: Finding | null;
  onClose: () => void;
}

export function RootCausePanel({ finding, onClose }: Props) {
  if (!finding) return null;

  const isAlert = finding.route === "alert";
  const baseC = finding.type === "semantic_duplicate" ? theme.amber : theme.red;
  const routeC = isAlert ? theme.red : theme.green;

  const evidence =
    finding.evidence.similarity != null
      ? finding.evidence.similarity.toFixed(2)
      : finding.evidence.convergence || "none";
  const evidenceLabel = finding.type === "semantic_duplicate" ? "cosine sim" : finding.type === "cycle" ? "convergence" : "similarity";

  const modelDisplay = renderModelList(finding.models_involved);

  return (
    <div style={{ background: theme.surface, border: `1px solid ${theme.borderStrong}`, borderRadius: 8, padding: "15px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 12 }}>
        <span
          style={{
            fontFamily: theme.mono,
            fontSize: 9.5,
            fontWeight: 600,
            letterSpacing: "0.05em",
            color: baseC,
            background: hexA(baseC, 0.13),
            border: `1px solid ${hexA(baseC, 0.3)}`,
            padding: "2px 7px",
            borderRadius: 4,
          }}
        >
          {isAlert ? "ALERT → SENTRY" : "CACHE → LANGCACHE"}
        </span>
        <span
          style={{
            fontFamily: theme.mono,
            fontSize: 9.5,
            fontWeight: 600,
            letterSpacing: "0.05em",
            color: baseC,
            background: "transparent",
            border: `1px solid ${hexA(baseC, 0.3)}`,
            padding: "2px 7px",
            borderRadius: 4,
          }}
        >
          {finding.type.toUpperCase()}
        </span>
        <span style={{ flex: 1 }} />
        <div
          onClick={onClose}
          style={{
            width: 22,
            height: 22,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--gt-dim)",
            cursor: "pointer",
            fontSize: 12,
            border: `1px solid ${theme.border}`,
            borderRadius: 5,
          }}
        >
          ✕
        </div>
      </div>

      <div style={{ fontSize: 14, color: theme.text, lineHeight: 1.45, fontWeight: 500, marginBottom: 6 }}>
        {plainFor(finding)}
      </div>
      <div style={{ fontSize: 12.5, color: "var(--gt-sec)", lineHeight: 1.5, marginBottom: 14 }}>{finding.description}</div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "11px 14px",
          paddingTop: 13,
          borderTop: `1px solid ${theme.border}`,
        }}
      >
        <Cell value={formatDemoUsd(finding.dollar_cost)} valueColor={baseC} label="attributed cost" mono large />
        <Cell value={finding.count + "×"} label="occurrences" mono large />
        <Cell value={evidence} label={evidenceLabel} mono />
        <Cell value={isAlert ? "Sentry" : "LangCache"} valueColor={routeC} label="routed to" mono />
        <Cell value={modelDisplay} label="models involved" mono fullSpan />
      </div>
    </div>
  );
}

function Cell({
  value,
  label,
  valueColor,
  mono,
  large,
  fullSpan,
}: {
  value: string;
  label: string;
  valueColor?: string;
  mono?: boolean;
  large?: boolean;
  fullSpan?: boolean;
}) {
  return (
    <div style={fullSpan ? { gridColumn: "1 / span 2" } : undefined}>
      <div
        style={{
          fontFamily: mono ? theme.mono : theme.sans,
          fontSize: large ? 22 : 14,
          fontWeight: large ? 600 : 400,
          color: valueColor ?? theme.text,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 10, color: "var(--gt-dim)", marginTop: 2 }}>{label}</div>
    </div>
  );
}

function plainFor(f: Finding): string {
  if (f.type === "repetition") return "Sub-agents asked the same question — cache candidate.";
  if (f.type === "semantic_duplicate") return "Same subgoal phrased two ways — semantic candidate.";
  return "Output never changing — this is an incident, not a cache.";
}

function renderModelList(models: string[]): string {
  if (!models.length) return "—";
  const labels = models.map(shortLabel);
  if (labels.length <= 2) return labels.join(", ");
  return `${labels[0]}, ${labels[1]} +${labels.length - 2} more`;
}
