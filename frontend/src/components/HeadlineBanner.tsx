import { theme } from "../theme";

interface Props {
  diagnosed: boolean;
  totalCost: number;
  wastedCost: number;
  wastePct: number;
  findingCount: number;
  onToggleDiagnose: () => void;
}

const fmt = (n: number) => "$" + n.toFixed(2);

export function HeadlineBanner({ diagnosed, totalCost, wastedCost, wastePct, findingCount, onToggleDiagnose }: Props) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "16px 22px",
        borderBottom: `1px solid ${theme.border}`,
        background: theme.bg,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 14, minWidth: 0 }}>
        {diagnosed ? (
          <div style={{ display: "flex", alignItems: "baseline", gap: 11 }}>
            <span
              style={{
                fontFamily: theme.mono,
                fontSize: 38,
                fontWeight: 600,
                color: theme.red,
                letterSpacing: "-0.03em",
                lineHeight: 1,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {fmt(wastedCost)}
            </span>
            <span style={{ fontSize: 15, color: "var(--gt-sec)" }}>wasted of</span>
            <span
              style={{
                fontFamily: theme.mono,
                fontSize: 24,
                fontWeight: 500,
                color: theme.text,
                letterSpacing: "-0.02em",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {fmt(totalCost)}
            </span>
            <span style={{ fontSize: 15, color: "var(--gt-sec)" }}>total</span>
            <span
              style={{
                fontFamily: theme.mono,
                fontSize: 13,
                color: theme.redSoft,
                background: "rgba(248,113,113,0.08)",
                border: "1px solid rgba(248,113,113,0.2)",
                padding: "2px 8px",
                borderRadius: 5,
                marginLeft: 4,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {Math.round(wastePct)}%
            </span>
            <span style={{ fontFamily: theme.mono, fontSize: 12, color: "var(--gt-dim)" }}>
              · {findingCount} findings
            </span>
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "baseline", gap: 11 }}>
            <span
              style={{
                fontFamily: theme.mono,
                fontSize: 34,
                fontWeight: 600,
                color: theme.text,
                letterSpacing: "-0.03em",
                lineHeight: 1,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {fmt(totalCost)}
            </span>
            <span style={{ fontSize: 14, color: "var(--gt-dim)" }}>total spend · run looks fine — nobody knows why</span>
          </div>
        )}
      </div>
      <div style={{ flex: 1 }} />
      <div
        onClick={onToggleDiagnose}
        style={{
          display: "flex",
          alignItems: "center",
          height: 34,
          padding: "0 16px",
          borderRadius: 7,
          fontSize: 12.5,
          fontWeight: 600,
          cursor: "pointer",
          whiteSpace: "nowrap",
          background: diagnosed ? "transparent" : theme.green,
          color: diagnosed ? "var(--gt-sec)" : "#08130C",
          border: diagnosed ? `1px solid ${theme.border}` : `1px solid ${theme.green}`,
        }}
      >
        {diagnosed ? "Reset to raw run" : "▸ Run diagnosis"}
      </div>
    </div>
  );
}
