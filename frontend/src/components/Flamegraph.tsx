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

interface GroupShape {
  id: string;
  members: Span[];
  left: number;
  width: number;
  top: number;
  height: number;
  hasRed: boolean;
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
// Only the most recent slice of the trace is shown — spans whose end_time is
// older than this window (measured back from the latest span) are hidden.
const WINDOW_MS = 60_000;
// When an overlap-connected cluster at one depth would stack more than this many
// lanes deep, it collapses into a single "N calls" box instead of a tall stack.
const COLLAPSE_LANE_THRESHOLD = 3;

// A laid-out unit fed to the lane packer: either a single span or a collapsed
// cluster of spans rendered as one box.
type LayoutItem =
  | { kind: "span"; span: Span; depth: number }
  | {
      kind: "group";
      id: string;
      depth: number;
      start: number;
      end: number;
      members: Span[];
      hasRed: boolean;
    };

export function Flamegraph({ spans, findings, diagnosed, reran, selectedFinding, onSelectFinding }: Props) {
  // The chart body is fluid (bars are sized in %). We measure its rendered width
  // only so the lane packer can translate the few-pixel collision gap into the
  // time domain; the layout otherwise stays resolution-independent.
  const bodyRef = useRef<HTMLDivElement>(null);
  const [bodyWidth, setBodyWidth] = useState(900);

  // Collapsed clusters the user has clicked to expand back into individual bars.
  // Keys are derived from span ids so they stay stable across polling re-renders;
  // ids for clusters that no longer exist are simply ignored.
  const [expandedClusters, setExpandedClusters] = useState<Set<string>>(new Set());
  const toggleCluster = (id: string) =>
    setExpandedClusters((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  // Show only the last minute of activity, measured back from the latest span's
  // end_time (the trace's own clock, so loaded historical traces still render).
  const windowedSpans = useMemo(() => {
    if (!spans.length) return spans;
    const latestEnd = Math.max(...spans.map((s) => s.end_time));
    const cutoff = latestEnd - WINDOW_MS;
    return spans.filter((s) => s.end_time >= cutoff);
  }, [spans]);
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
    for (const s of windowedSpans) parents.set(s.span_id, s.parent_span_id);
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
    for (const s of windowedSpans) {
      const d = depth(s.span_id, new Set());
      map.set(s.span_id, d);
      if (d > maxDepth) maxDepth = d;
    }
    const start = windowedSpans.length ? Math.min(...windowedSpans.map((s) => s.start_time)) : 0;
    const end = windowedSpans.length ? Math.max(...windowedSpans.map((s) => s.end_time)) : 1;
    return { depthBySpan: map, depthCount: maxDepth + 1, totalMs: Math.max(end - start, 1) };
  }, [windowedSpans]);

  // Reverse-lookup: span_id -> finding so we can color quickly.
  const findingBySpan = useMemo(() => {
    const m = new Map<string, Finding>();
    for (const f of findings) for (const sid of f.span_ids) m.set(sid, f);
    return m;
  }, [findings]);

  // Collision-free lane layout: group by depth, pack overlapping spans into
  // separate lanes, and stack depth blocks so nothing overlaps. See spanLayout.ts.
  //
  // Before packing we collapse any overlap-connected cluster at a depth that
  // would stack more than COLLAPSE_LANE_THRESHOLD lanes deep into a single
  // "N calls" box (unless the user has expanded it). Because a connected cluster
  // is disjoint from every other cluster at its depth, feeding the packer one
  // interval spanning the cluster makes it occupy a single lane, so the chart
  // shrinks vertically with no changes to the generic packer.
  const { layout, barById, groupById } = useMemo(() => {
    const offsetStart = windowedSpans.length ? Math.min(...windowedSpans.map((s) => s.start_time)) : 0;
    // Match the packer's pixel→time gap so cluster breaks line up with lane breaks.
    const gapMs = bodyWidth > 0 ? (COLLISION_GAP_PX / bodyWidth) * totalMs : 0;

    const items = buildLayoutItems(
      windowedSpans,
      (s) => depthBySpan.get(s.span_id) ?? 0,
      gapMs,
      expandedClusters,
      (s) => isRedSpan(s, findingBySpan, diagnosed, reran)
    );

    const lay = computeSpanLayout<LayoutItem>(
      items,
      { offsetStart, totalMs, widthPx: bodyWidth },
      {
        rowHeight: ROW_H,
        laneGap: LANE_GAP,
        depthGap: DEPTH_GAP,
        collisionGapPx: COLLISION_GAP_PX,
        getStart: (it) => (it.kind === "span" ? it.span.start_time : it.start),
        getEnd: (it) => (it.kind === "span" ? it.span.end_time : it.end),
        getDepth: (it) => it.depth,
      }
    );

    const map = new Map<string, BarShape & { positioned: LaidOutSpan<LayoutItem> }>();
    const groups = new Map<string, GroupShape>();
    for (const p of lay.spans) {
      const it = p.span;
      if (it.kind === "group") {
        groups.set(it.id, {
          id: it.id,
          members: it.members,
          hasRed: it.hasRed,
          left: p.leftPct,
          width: p.widthPct,
          top: p.top,
          height: p.height,
        });
        continue;
      }
      const sp = it.span;
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
    return { layout: lay, barById: map, groupById: groups };
  }, [windowedSpans, findingBySpan, diagnosed, reran, totalMs, depthBySpan, selectedFinding, bodyWidth, expandedClusters]);

  const bars = useMemo(() => Array.from(barById.values()), [barById]);
  const groups = useMemo(() => Array.from(groupById.values()), [groupById]);

  // Axis ticks (0–100%).
  const axisTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    label: ((f * totalMs) / 1000).toFixed(0) + "s",
    pct: f * 100,
  }));

  // The runaway loop marker — anchored to the runaway span's actual lane so it
  // tracks the lane-packed layout instead of a hard-coded depth row. When that
  // span is hidden inside a collapsed cluster, fall back to anchoring on the
  // group box so the marker never disappears.
  const runaway = findings.find((f) => f.severity === "runaway");
  const runawaySpanId = runaway?.span_ids[0];
  const runawayAnchor =
    (runawaySpanId ? barById.get(runawaySpanId) : null) ??
    (runawaySpanId ? groups.find((g) => g.members.some((m) => m.span_id === runawaySpanId)) : null) ??
    null;
  const runawayLeftPct = runawayAnchor ? runawayAnchor.left : null;
  const runawayTop = runawayAnchor ? runawayAnchor.top + runawayAnchor.height + 4 : 0;

  // Chart height follows the computed lane count, with room for the marker chip.
  const markerSpace = diagnosed && runawayAnchor ? 26 : 0;
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
          {windowedSpans.length} spans · last 60s · nested by call depth
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

        {groups.map((g) => {
          // Red when any member is red (diagnosed cycle/runaway or un-rerun
          // repetition); otherwise neutral grey. Clicking expands the cluster.
          const red = diagnosed && g.hasRed;
          const bg = red ? hexA("#F87171", 0.4) : "#222B35";
          const bd = red ? hexA("#F87171", 0.5) : "#323C48";
          const tx = red ? "#F2B4B4" : "var(--gt-mut)";
          return (
            <div
              key={g.id}
              onClick={() => toggleCluster(g.id)}
              title={`${g.members.length} overlapping calls — click to expand`}
              style={{
                position: "absolute",
                left: g.left + "%",
                width: g.width + "%",
                top: g.top,
                height: g.height,
                background: bg,
                border: `1.5px solid ${bd}`,
                borderRadius: 3,
                cursor: "pointer",
                overflow: "hidden",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                boxSizing: "border-box",
                transition: "filter 0.12s",
              }}
            >
              <span
                style={{
                  fontFamily: theme.mono,
                  fontSize: 11,
                  fontWeight: 700,
                  color: tx,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  padding: "0 7px",
                }}
              >
                {g.members.length} calls
              </span>
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

// Whether a span renders "red" (a problem worth surfacing) — mirrors barColor:
// diagnosed repetition that hasn't been rerun, or a cycle/runaway. Semantic
// duplicates are amber (not red) and rerun repetitions are green (not red).
function isRedSpan(
  span: Span,
  findingBySpan: Map<string, Finding>,
  diagnosed: boolean,
  reran: boolean
): boolean {
  if (!diagnosed) return false;
  const f = findingBySpan.get(span.span_id);
  if (!f) return false;
  if (f.type === "semantic_duplicate") return false;
  if (f.type === "repetition") return !reran;
  return true; // cycle / runaway
}

// Bucket spans by depth and, within each depth, find overlap-connected clusters.
// A cluster whose first-fit lane count exceeds COLLAPSE_LANE_THRESHOLD (and isn't
// in `expanded`) collapses into one "group" item; everything else passes through
// as individual "span" items. Output order is not significant — the packer sorts.
function buildLayoutItems(
  spans: Span[],
  getDepth: (s: Span) => number,
  gapMs: number,
  expanded: Set<string>,
  isRed: (s: Span) => boolean
): LayoutItem[] {
  const byDepth = new Map<number, Span[]>();
  for (const s of spans) {
    const d = Math.max(0, getDepth(s));
    const bucket = byDepth.get(d);
    if (bucket) bucket.push(s);
    else byDepth.set(d, [s]);
  }

  const items: LayoutItem[] = [];
  for (const [depth, group] of byDepth) {
    const sorted = group
      .slice()
      .sort((a, b) => a.start_time - b.start_time || a.end_time - b.end_time);

    // Split into overlap-connected clusters: a new cluster starts when a span
    // begins at/after the running max end (plus the same gap the packer uses).
    let cluster: Span[] = [];
    let clusterMaxEnd = -Infinity;
    const flush = () => {
      if (cluster.length) emitCluster(items, depth, cluster, gapMs, expanded, isRed);
      cluster = [];
      clusterMaxEnd = -Infinity;
    };
    for (const s of sorted) {
      if (cluster.length && s.start_time >= clusterMaxEnd) flush();
      cluster.push(s);
      clusterMaxEnd = Math.max(clusterMaxEnd, s.end_time + gapMs);
    }
    flush();
  }
  return items;
}

function emitCluster(
  out: LayoutItem[],
  depth: number,
  cluster: Span[],
  gapMs: number,
  expanded: Set<string>,
  isRed: (s: Span) => boolean
) {
  // Lanes needed = first-fit lane count, same packing the renderer would do.
  const laneEnds: number[] = [];
  for (const s of cluster) {
    let placed = -1;
    for (let l = 0; l < laneEnds.length; l++) {
      if (s.start_time >= laneEnds[l]) {
        placed = l;
        break;
      }
    }
    if (placed === -1) {
      placed = laneEnds.length;
      laneEnds.push(0);
    }
    laneEnds[placed] = s.end_time + gapMs;
  }
  const lanesNeeded = laneEnds.length;
  const id = `g:${depth}:${cluster[0].span_id}`;

  if (lanesNeeded > COLLAPSE_LANE_THRESHOLD && !expanded.has(id)) {
    out.push({
      kind: "group",
      id,
      depth,
      start: Math.min(...cluster.map((s) => s.start_time)),
      end: Math.max(...cluster.map((s) => s.end_time)),
      members: cluster,
      hasRed: cluster.some(isRed),
    });
  } else {
    for (const s of cluster) out.push({ kind: "span", span: s, depth });
  }
}

function barColor(finding: Finding | null, diagnosed: boolean, reran: boolean) {
  if (!diagnosed || !finding) {
    return { bg: "#222B35", bd: "#323C48", tx: "var(--gt-mut)" };
  }
  // After rerun, every LangCache-routed finding is served from cache → green.
  // Alert-routed findings (the runaway loop → Sentry) are never cached → stay red.
  if (reran && finding.route === "cache") {
    return { bg: hexA("#4ADE80", 0.16), bd: hexA("#4ADE80", 0.5), tx: theme.greenSoft };
  }
  if (finding.type === "repetition") {
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
