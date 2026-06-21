import { hexA, theme } from "../theme";
import type { Finding } from "../types";

interface Props {
  findings: Finding[];
  selectedFinding: string | null;
  onSelect: (id: string) => void;
}

export function FindingsList({ findings, selectedFinding, onSelect }: Props) {
  const cache = findings.filter((f) => f.route === "cache");
  const alerts = findings.filter((f) => f.route === "alert");

  return (
    <div style={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 8, padding: "14px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <span
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.09em",
            color: "var(--gt-sec)",
            fontWeight: 600,
          }}
        >
          Findings
        </span>
        <span style={{ fontFamily: theme.mono, fontSize: 11, color: "var(--gt-dimmer)" }}>{findings.length}</span>
      </div>

      <GroupHeader icon="⤴" label="Cache → LangCache" color={theme.blue} />
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
        {cache.map((f) => (
          <Card key={f.finding_id} finding={f} selected={selectedFinding === f.finding_id} onClick={() => onSelect(f.finding_id)} />
        ))}
      </div>

      <GroupHeader icon="⚠" label="Alert → Sentry" color={theme.red} />
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {alerts.map((f) => (
          <Card key={f.finding_id} finding={f} selected={selectedFinding === f.finding_id} onClick={() => onSelect(f.finding_id)} />
        ))}
      </div>
    </div>
  );
}

function GroupHeader({ icon, label, color }: { icon: string; label: string; color: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 9 }}>
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 16,
          height: 16,
          borderRadius: 4,
          background: hexA(color, 0.14),
          color,
          fontSize: 9,
        }}
      >
        {icon}
      </span>
      <span
        style={{
          fontFamily: theme.mono,
          fontSize: 10,
          letterSpacing: "0.06em",
          color: "var(--gt-dim)",
          textTransform: "uppercase",
        }}
      >
        {label}
      </span>
      <div style={{ flex: 1, height: 1, background: theme.borderSoft }} />
    </div>
  );
}

function Card({ finding, selected, onClick }: { finding: Finding; selected: boolean; onClick: () => void }) {
  const isAlert = finding.route === "alert";
  const baseC = finding.type === "semantic_duplicate" ? theme.amber : theme.red;
  const routeC = isAlert ? theme.red : theme.green;
  const title = titleFor(finding);
  const sub = subFor(finding);
  return (
    <div
      onClick={onClick}
      style={{
        padding: "11px 12px",
        borderRadius: 7,
        cursor: "pointer",
        background: theme.surfaceAlt,
        border: `1px solid ${selected ? theme.text : theme.border}`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}>
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: 2,
            background: hexA(baseC, 0.4),
            border: `1px solid ${hexA(baseC, 0.7)}`,
            display: "inline-block",
            flex: "0 0 auto",
          }}
        />
        <span style={{ fontFamily: theme.mono, fontSize: 12.5, color: theme.text, fontWeight: 500 }}>{title}</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontFamily: theme.mono, fontSize: 13, color: theme.red, fontVariantNumeric: "tabular-nums" }}>
          ${finding.dollar_cost.toFixed(2)}
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 11, color: "var(--gt-sec)", lineHeight: 1.4, flex: 1 }}>{sub}</span>
        <span
          style={{
            fontFamily: theme.mono,
            fontSize: 9.5,
            color: routeC,
            background: hexA(routeC, 0.1),
            border: `1px solid ${hexA(routeC, 0.24)}`,
            padding: "2px 6px",
            borderRadius: 4,
            whiteSpace: "nowrap",
            flex: "0 0 auto",
          }}
        >
          {isAlert ? "⚠ Sentry" : "⤴ LangCache"}
        </span>
      </div>
      {isAlert && finding.alert_fired && (
        <div
          className="rdt-alert"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginTop: 9,
            padding: "6px 9px",
            background: "#160F11",
            border: "1px solid rgba(248,113,113,0.32)",
            borderRadius: 5,
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: theme.red, display: "inline-block" }} />
          <span style={{ fontFamily: theme.mono, fontSize: 10.5, color: theme.redSoft }}>
            Sentry incident fired · loop-detected
          </span>
        </div>
      )}
    </div>
  );
}

// Tight, design-faithful copy derived from finding fields so we don't depend on
// a backend `title`/`sub` extension (§3d in the integration plan).
function titleFor(f: Finding): string {
  if (f.type === "repetition") return `${f.count}× ${toolFromDesc(f) ?? "duplicate calls"}`;
  if (f.type === "semantic_duplicate") return "duplicate subgoal";
  return `${f.count}× ${toolFromDesc(f) ?? "loop"}`;
}

function subFor(f: Finding): string {
  if (f.type === "repetition") return `Same query across ${distinctAgents(f) || f.count} sub-agents`;
  if (f.type === "semantic_duplicate") return "Two prompts, one intent";
  return "Output never converges";
}

function toolFromDesc(f: Finding): string | null {
  // descriptions look like: "web_search called 3x with identical args ..."
  const m = f.description.match(/^(\w+)/);
  return m ? m[1] : null;
}

function distinctAgents(f: Finding): number | null {
  // Heuristic: count comma-separated names after "across N agents:"
  const m = f.description.match(/across (\d+) agents/);
  return m ? Number(m[1]) : null;
}
