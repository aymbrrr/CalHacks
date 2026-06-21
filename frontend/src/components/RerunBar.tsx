import { theme } from "../theme";
import type { RerunResponse } from "../types";

interface Props {
  reran: boolean;
  rerunData: RerunResponse | null;
  originalCost: number;
  onRerun: () => void;
}

const fmt = (n: number) => "$" + n.toFixed(2);

export function RerunBar({ reran, rerunData, originalCost, onRerun }: Props) {
  return (
    <div
      style={{
        background: theme.surface,
        border: `1px solid ${theme.border}`,
        borderRadius: 8,
        padding: "14px 17px",
        display: "flex",
        alignItems: "center",
        gap: 16,
      }}
    >
      <div
        onClick={reran ? undefined : onRerun}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 7,
          height: 36,
          padding: "0 16px",
          borderRadius: 7,
          fontSize: 12.5,
          fontWeight: 600,
          cursor: reran ? "default" : "pointer",
          whiteSpace: "nowrap",
          background: reran ? theme.surface : theme.blue,
          color: reran ? theme.greenSoft : "#04141A",
          border: reran ? `1px solid ${theme.border}` : "none",
        }}
      >
        {reran ? "✓ cache applied" : "▸ Re-run with cache"}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        {reran && rerunData ? (
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <span
              style={{
                fontFamily: theme.mono,
                fontSize: 18,
                color: "var(--gt-dimmer)",
                textDecoration: "line-through",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {fmt(originalCost)}
            </span>
            <span style={{ color: theme.green, fontSize: 14 }}>→</span>
            <span
              style={{
                fontFamily: theme.mono,
                fontSize: 22,
                fontWeight: 600,
                color: theme.green,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {fmt(rerunData.cached_cost)}
            </span>
            <span
              style={{
                fontFamily: theme.mono,
                fontSize: 12,
                color: theme.green,
                background: "rgba(74,222,128,0.12)",
                border: "1px solid rgba(74,222,128,0.3)",
                padding: "2px 8px",
                borderRadius: 5,
              }}
            >
              saved {fmt(rerunData.saved)}
            </span>
            <span style={{ fontSize: 12, color: "var(--gt-dim)" }}>
              {rerunData.cache_hits.length}× served from LangCache · verified read-only
            </span>
          </div>
        ) : (
          <span style={{ fontSize: 12.5, color: "var(--gt-dim)" }}>
            Serve the cacheable duplicates from LangCache and watch the total drop. The runaway stays — it routes to an alert, not the cache.
          </span>
        )}
      </div>
    </div>
  );
}
