import { useEffect, useMemo, useRef, useState } from "react";
import { hexA, theme } from "../theme";
import { formatDemoUsd } from "../api/displayMoney";
import { shortLabel } from "../api/modelInfo";
import type { Finding, Span } from "../types";
import { computeSpanLayout, type LaidOutSpan } from "./spanLayout";

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
// Lane packing geometry: lanes within a depth sit close together, while depth
// blocks get a little extra breathing room so the hierarchy stays legible.
const LANE_GAP = 4;
const DEPTH_GAP = 9;
const COLLISION_GAP_PX = 3;
// Below this width (% of axis) a bar is too narrow for a readable label, so we
// drop the text and rely on the hover tooltip instead.
const LABEL_MIN_WIDTH_PCT = 6;

export function Flamegraph({ spans, findings, diagnosed, reran, selectedFinding, onSelectFinding }: Props) {
  // The chart body is fluid (bars are sized in %). We measure its rendered width
  // only so the lane packer can translate the few-pixel collision gap into the
  // time domain; the layout otherwise stays resolution-independent.
  const bodyRef = useRef<HTMLDivElement>(null);
  const [bodyWidth, setBodyWidth] = useState(900);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const update = () => setBodyWidth(el.clientWidth || 900);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Compute every span's depth from parent_span_id.
  //
  // The bundled demo trace contains an intentional cycle (s_07 ↔ s_08 ↔ s_09)
  // — that's literally the cycle the backend's detector reports as a finding.
  // The walker MUST tolerate cycles in the parent chain or React stack-
  // overflows mid-render. We break the cycle by tracking in-progress ids and
  // treating any back-edge as depth 0 (treating the cycle member as a root).
  const { depthBySpan, totalMs } = useMemo(() => {
    const parents = new Map<string, string | null>();
    for (const s of spans) parents.set(s.span_id, s.parent_span_id);
    const memo = new Map<string, number>();
    const depth = (id: string, inFlight: Set<string>): number => {
      const cached = memo.get(id);
      if (cached !== undefined) return cached;
      if (inFlight.has(id)) return 0; // cycle — stop walking
      inFlight.add(id);
      const p = parents.get(id) ?? null;
      const d = p && parents.has(p) ? depth(p, inFlight) + 1 : 0;
      inFlight.delete(id);
      memo.set(id, d);
      return d;
    };
    const map = new Map<string, number>();
    let maxDepth = 0;
    for (const s of spans) {
      const d = depth(s.span_id, new Set());
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

  // Collision-free lane layout: group by depth, pack overlapping spans into
  // separate lanes, and stack depth blocks so nothing overlaps. See spanLayout.ts.
  const { layout, barById } = useMemo(() => {
    const offsetStart = spans.length ? Math.min(...spans.map((s) => s.start_time)) : 0;
    const lay = computeSpanLayout<Span>(
      spans,
      { offsetStart, totalMs, widthPx: bodyWidth },
      {
        rowHeight: ROW_H,
        laneGap: LANE_GAP,
        depthGap: DEPTH_GAP,
        collisionGapPx: COLLISION_GAP_PX,
        getStart: (s) => s.start_time,
        getEnd: (s) => s.end_time,
        getDepth: (s) => depthBySpan.get(s.span_id) ?? 0,
      }
    );

    const map = new Map<string, BarShape & { positioned: LaidOutSpan<Span> }>();
    for (const p of lay.spans) {
      const sp = p.span;
      const finding = findingBySpan.get(sp.span_id) ?? null;
      const color = barColor(finding, diagnosed, reran);
      const isRoot = p.depth === 0;
      const label = isRoot
        ? sp.name
        : sp.kind === "agent"
        ? sp.agent_name
        : sp.name.replace("tool:", "").replace("llm:", "");
      map.set(sp.span_id, {
        span: sp,
        left: p.leftPct,
        width: p.widthPct,
        top: p.top,
        height: p.height,
        color,
        selected: !!finding && finding.finding_id === selectedFinding && diagnosed,
        isRoot,
        label,
        positioned: p,
      });
    }
    return { layout: lay, barById: map };
  }, [spans, findingBySpan, diagnosed, reran, totalMs, depthBySpan, selectedFinding, bodyWidth]);

  const bars = useMemo(() => Array.from(barById.values()), [barById]);

  // Axis ticks (0–100%).
  const axisTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    label: ((f * totalMs) / 1000).toFixed(0) + "s",
    pct: f * 100,
  }));

  // The runaway loop marker — anchored to the runaway span's actual lane so it
  // tracks the lane-packed layout instead of a hard-coded depth row.
  const runaway = findings.find((f) => f.severity === "runaway");
  const runawayBar = runaway ? barById.get(runaway.span_ids[0]) : null;
  const runawayLeftPct = runawayBar ? runawayBar.left : null;
  const runawayTop = runawayBar ? runawayBar.top + runawayBar.height + 4 : 0;

  // Chart height follows the computed lane count, with room for the marker chip.
  const markerSpace = diagnosed && runawayBar ? 26 : 0;
  const containerHeight = Math.max(layout.totalHeight + markerSpace, ROW_H) + 4;

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

      <div ref={bodyRef} style={{ position: "relative", height: containerHeight, width: "100%" }}>
        {bars.map((b) => {
          const tip = `${b.span.name}  ·  ${b.span.agent_name}\n${shortLabel(b.span.model)} · ${b.span.tokens.input + b.span.tokens.output} tok · ${(
            (b.span.end_time - b.span.start_time) / 1000
          ).toFixed(2)}s · ${formatDemoUsd(b.span.cost_usd)}\nin: ${b.span.input}`;
          const finding = findingBySpan.get(b.span.span_id);
          const wideEnough = b.width > LABEL_MIN_WIDTH_PCT;
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
                boxSizing: "border-box",
                boxShadow: b.selected ? `0 0 0 1.5px ${b.color.bd}` : "none",
                transition: "filter 0.12s",
              }}
            >
              {wideEnough && (
                <span
                  style={{
                    fontFamily: theme.mono,
                    fontSize: 10.5,
                    color: b.color.tx,
                    // Clip the label inside the bar so it never spills into a neighbour.
                    flex: 1,
                    minWidth: 0,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    padding: "0 7px",
                    fontWeight: b.isRoot ? 600 : 400,
                  }}
                >
                  {b.label}
                </span>
              )}
            </div>
          );
        })}

        {diagnosed && runawayLeftPct != null && (
          <div
            style={{
              position: "absolute",
              left: `calc(${runawayLeftPct}% )`,
              top: runawayTop,
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
