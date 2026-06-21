import { theme } from "../theme";
import { formatDemoUsd } from "../api/displayMoney";
import type { RerunResponse } from "../types";

interface Props {
  reran: boolean;
  rerunData: RerunResponse | null;
  originalCost: number;
  onRerun: () => void;
}

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
        {reran ? "✓ savings preview" : "▸ Preview cache savings"}
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
              {formatDemoUsd(originalCost)}
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
              {formatDemoUsd(rerunData.cached_cost)}
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
              est. saved {formatDemoUsd(rerunData.saved)}
            </span>
            <span style={{ fontSize: 12, color: "var(--gt-dim)" }}>
              {rerunData.cache_hits.length}× cacheable · estimated savings
            </span>
          </div>
        ) : (
          <span style={{ fontSize: 12.5, color: "var(--gt-dim)" }}>
            Preview the savings from the cacheable duplicates served from LangCache. The runaway stays.It routes to an alert, not the cache.
          </span>
        )}
      </div>
    </div>
  );
}
