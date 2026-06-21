import { useMemo } from "react";
import { hexA, theme } from "../theme";
import { shortLabel } from "../api/modelInfo";
import type { Finding, Span } from "../types";

interface Props {
  spans: Span[];
  findings: Finding[];
  diagnosed: boolean;
  reran: boolean;
  selectedFinding: string | null;
  onSelectFinding: (id: string | null) => void;
}

interface BarShape {
  span: Span;
  left: number;
  width: number;
  top: number;
  height: number;
  color: { bg: string; bd: string; tx: string };
  selected: boolean;
  isRoot: boolean;
  label: string;
}

const ROW_H = 30;
const GAP = 5;

export function Flamegraph({ spans, findings, diagnosed, reran, selectedFinding, onSelectFinding }: Props) {
  // Compute every span's depth from parent_span_id.
  const { depthBySpan, depthCount, totalMs } = useMemo(() => {
    const parents = new Map<string, string | null>();
    for (const s of spans) parents.set(s.span_id, s.parent_span_id);
    const memo = new Map<string, number>();
    const depth = (id: string): number => {
      if (memo.has(id)) return memo.get(id)!;
      const p = parents.get(id) ?? null;
      const d = p && parents.has(p) ? depth(p) + 1 : 0;
      memo.set(id, d);
      return d;
    };
    const map = new Map<string, number>();
    let maxDepth = 0;
    for (const s of spans) {
      const d = depth(s.span_id);
      map.set(s.span_id, d);
      if (d > maxDepth) maxDepth = d;
    }
    const start = Math.min(...spans.map((s) => s.start_time));
    const end = Math.max(...spans.map((s) => s.end_time));
    return { depthBySpan: map, depthCount: maxDepth + 1, totalMs: Math.max(end - start, 1) };
  }, [spans]);

  // Reverse-lookup: span_id -> finding so we can color quickly.
  const findingBySpan = useMemo(() => {
    const m = new Map<string, Finding>();
    for (const f of findings) for (const sid of f.span_ids) m.set(sid, f);
    return m;
  }, [findings]);

  const bars: BarShape[] = useMemo(() => {
    const offsetStart = Math.min(...spans.map((s) => s.start_time));
    return spans.map((sp) => {
      const finding = findingBySpan.get(sp.span_id) ?? null;
      const color = barColor(finding, diagnosed, reran);
      const left = ((sp.start_time - offsetStart) / totalMs) * 100;
      const width = Math.max(((sp.end_time - sp.start_time) / totalMs) * 100, 0.5);
      const depth = depthBySpan.get(sp.span_id) ?? 0;
      const top = depth * (ROW_H + GAP);
      const isRoot = depth === 0;
      const label = isRoot
        ? sp.name
        : sp.kind === "agent"
        ? sp.agent_name
        : sp.name.replace("tool:", "").replace("llm:", "");
      return {
        span: sp,
        left,
        width,
        top,
        height: ROW_H,
        color,
        selected: !!finding && finding.finding_id === selectedFinding && diagnosed,
        isRoot,
        label,
      };
    });
  }, [spans, findingBySpan, diagnosed, reran, totalMs, depthBySpan, selectedFinding]);

  // Axis ticks (0–100%).
  const axisTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    label: ((f * totalMs) / 1000).toFixed(0) + "s",
    pct: f * 100,
  }));

  // The runaway loop marker.
  const runaway = findings.find((f) => f.severity === "runaway");
  const runawayLeftSpan = runaway ? spans.find((s) => s.span_id === runaway.span_ids[0]) : null;
  const runawayLeftPct = runawayLeftSpan
    ? ((runawayLeftSpan.start_time - Math.min(...spans.map((s) => s.start_time))) / totalMs) * 100
    : null;

  const containerHeight = depthCount * (ROW_H + GAP) + 18;

  return (
    <div
      style={{
        background: theme.surface,
        border: `1px solid ${theme.border}`,
        borderRadius: 8,
        padding: "15px 17px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <span
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.09em",
            color: "var(--gt-sec)",
            fontWeight: 600,
            whiteSpace: "nowrap",
          }}
        >
          Flamegraph
        </span>
        <span style={{ fontFamily: theme.mono, fontSize: 11, color: "var(--gt-dimmer)", whiteSpace: "nowrap" }}>
          {spans.length} spans · nested by call depth
        </span>
        <span style={{ flex: 1 }} />
        <Legend />
      </div>

      <div style={{ position: "relative", height: 14, marginBottom: 6 }}>
        {axisTicks.map((tk, i) => (
          <span
            key={i}
            style={{
              position: "absolute",
              left: tk.pct + "%",
              transform: tk.pct === 100 ? "translateX(-100%)" : tk.pct === 0 ? "none" : "translateX(-50%)",
              fontFamily: theme.mono,
              fontSize: 9.5,
              color: "var(--gt-dimmer)",
            }}
          >
            {tk.label}
          </span>
        ))}
      </div>

      <div style={{ position: "relative", height: containerHeight, width: "100%" }}>
        {bars.map((b) => {
          const tip = `${b.span.name}  ·  ${b.span.agent_name}\n${shortLabel(b.span.model)} · ${b.span.tokens.input + b.span.tokens.output} tok · ${(
            (b.span.end_time - b.span.start_time) / 1000
          ).toFixed(2)}s · $${b.span.cost_usd.toFixed(3)}\nin: ${b.span.input}`;
          const finding = findingBySpan.get(b.span.span_id);
          const wideEnough = b.width > 7;
          return (
            <div
              key={b.span.span_id}
              onClick={() => onSelectFinding(finding ? finding.finding_id : null)}
              title={tip}
              style={{
                position: "absolute",
                left: b.left + "%",
                width: b.width + "%",
                top: b.top,
                height: b.height,
                background: b.color.bg,
                border: `1px solid ${b.color.bd}`,
                borderRadius: 3,
                cursor: finding ? "pointer" : "default",
                overflow: "hidden",
                display: "flex",
                alignItems: "center",
                boxShadow: b.selected ? `0 0 0 1.5px ${b.color.bd}` : "none",
                transition: "filter 0.12s",
              }}
            >
              <span
                style={{
                  fontFamily: theme.mono,
                  fontSize: 10.5,
                  color: b.color.tx,
                  whiteSpace: "nowrap",
                  padding: "0 7px",
                  opacity: wideEnough ? 1 : 0,
                  fontWeight: b.isRoot ? 600 : 400,
                }}
              >
                {b.label}
              </span>
            </div>
          );
        })}

        {diagnosed && runawayLeftPct != null && (
          <div
            style={{
              position: "absolute",
              left: `calc(${runawayLeftPct}% )`,
              top: 2 * (ROW_H + GAP) + ROW_H + 4,
              whiteSpace: "nowrap",
            }}
          >
            <span
              className="rdt-alert"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                fontFamily: theme.mono,
                fontSize: 10,
                fontWeight: 600,
                color: theme.redSoft,
                background: "#160F11",
                border: "1px solid rgba(248,113,113,0.35)",
                padding: "3px 8px",
                borderRadius: 5,
              }}
            >
              ⚠ runaway loop
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function barColor(finding: Finding | null, diagnosed: boolean, reran: boolean) {
  if (!diagnosed || !finding) {
    return { bg: "#222B35", bd: "#323C48", tx: "var(--gt-mut)" };
  }
  if (finding.type === "repetition") {
    if (reran) return { bg: hexA("#4ADE80", 0.16), bd: hexA("#4ADE80", 0.5), tx: theme.greenSoft };
    return { bg: hexA("#F87171", 0.16), bd: hexA("#F87171", 0.38), tx: theme.redSoft };
  }
  if (finding.type === "semantic_duplicate") {
    return {
      bg: `repeating-linear-gradient(45deg, ${hexA("#F59E0B", 0.28)} 0 5px, ${hexA("#F59E0B", 0.09)} 5px 10px)`,
      bd: hexA("#F59E0B", 0.5),
      tx: theme.amberSoft,
    };
  }
  // cycle / runaway
  return { bg: hexA("#F87171", 0.4), bd: hexA("#F87171", 0.5), tx: "#F2B4B4" };
}

function Legend() {
  const items = [
    { label: "legit", bg: "#222B35", bd: "#323C48" },
    { label: "waste→cache", bg: hexA("#F87171", 0.16), bd: hexA("#F87171", 0.4) },
    { label: "semantic", hatch: true },
    { label: "runaway→alert", bg: hexA("#F87171", 0.4), bd: hexA("#F87171", 0.5) },
  ];
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 13, flexWrap: "wrap" }}>
      {items.map((it) => (
        <span key={it.label} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <span
            style={{
              width: 11,
              height: 11,
              borderRadius: 2,
              border: `1px solid ${it.hatch ? hexA("#F59E0B", 0.55) : it.bd}`,
              background: it.hatch
                ? `repeating-linear-gradient(45deg, ${hexA("#F59E0B", 0.4)} 0 3px, ${hexA("#F59E0B", 0.12)} 3px 6px)`
                : it.bg,
              display: "inline-block",
            }}
          />
          <span style={{ fontFamily: theme.mono, fontSize: 9.5, color: "var(--gt-dim)" }}>{it.label}</span>
        </span>
      ))}
    </div>
  );
}
