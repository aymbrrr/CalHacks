/**
 * Collision-free lane layout for the flamegraph / trace timeline.
 *
 * The timeline keeps its time-axis semantics:
 *   - x position  = span start time
 *   - width       = span duration
 *
 * Spans are grouped by call depth. Within a depth, spans that overlap in time
 * can no longer share a single row without their rectangles colliding, so we
 * pack them into horizontal "lanes": each span is placed in the first lane
 * whose previous span has already ended (plus a small breathing gap). A depth
 * that needs N lanes occupies N rows of vertical space, and the next depth
 * starts below all of them, so rectangles from different depths never overlap.
 *
 * This module is deliberately free of React / theme / findings concerns: it
 * takes geometry in and returns geometry out, so it can be unit-tested in
 * isolation and the rendering component just consumes positioned spans.
 */

export interface TimeScale {
  /** Earliest start_time across all spans (epoch ms) — the x origin. */
  offsetStart: number;
  /** Total visible duration in ms (clamped to >= 1) — the x scale denominator. */
  totalMs: number;
  /**
   * Approximate rendered width of the timeline in px. Bars themselves are sized
   * in % so they stay fluid; this is used only to translate the pixel-sized
   * collision gap into the time domain when packing lanes.
   */
  widthPx: number;
}

export interface SpanLayoutOptions<T> {
  /** Height of a single lane / bar, in px. */
  rowHeight: number;
  /** Vertical gap between adjacent lanes within a depth, in px. */
  laneGap: number;
  /** Extra vertical gap inserted between depth blocks, in px. Defaults to laneGap. */
  depthGap?: number;
  /** Horizontal breathing room between two bars in the same lane, in px (2–4 is typical). */
  collisionGapPx: number;
  /** Minimum bar width as a % of the axis, so zero-duration spans stay clickable. Default 0.5. */
  minWidthPct?: number;
  /** Accessor for a span's start time. Defaults to reading `start_time`. */
  getStart?: (span: T) => number;
  /** Accessor for a span's end time. Defaults to reading `end_time`. */
  getEnd?: (span: T) => number;
  /** Accessor for a span's call depth (0 = root). Required. */
  getDepth: (span: T) => number;
}

export interface LaidOutSpan<T> {
  span: T;
  depth: number;
  /** Lane index within the depth (0-based). */
  lane: number;
  /** Left edge as a % of the axis width (0–100). */
  leftPct: number;
  /** Width as a % of the axis width (0–100). */
  widthPct: number;
  /** Top edge in px, measured from the top of the chart body. */
  top: number;
  /** Bar height in px (== options.rowHeight). */
  height: number;
}

export interface SpanLayout<T> {
  /** Positioned spans, in the same order as the input array. */
  spans: LaidOutSpan<T>[];
  /** Total chart-body height in px, sized to fit every lane of every depth. */
  totalHeight: number;
  /** lanesByDepth[d] = number of lanes used at depth d (0 for depths with no spans). */
  lanesByDepth: number[];
}

interface DefaultSpanShape {
  start_time: number;
  end_time: number;
}

/**
 * Compute a collision-free, lane-packed layout for a set of spans.
 *
 * @param spans   The spans to lay out (order is preserved in the output).
 * @param scale   Time → x-axis mapping plus the approximate render width.
 * @param options Geometry and accessors (see {@link SpanLayoutOptions}).
 */
export function computeSpanLayout<T>(
  spans: T[],
  scale: TimeScale,
  options: SpanLayoutOptions<T>
): SpanLayout<T> {
  const {
    rowHeight,
    laneGap,
    collisionGapPx,
    depthGap = laneGap,
    minWidthPct = 0.5,
    getDepth,
  } = options;

  const getStart = options.getStart ?? ((s) => (s as unknown as DefaultSpanShape).start_time);
  const getEnd = options.getEnd ?? ((s) => (s as unknown as DefaultSpanShape).end_time);

  const totalMs = Math.max(scale.totalMs, 1);
  // Translate the pixel gap into time units so the collision test can run in the
  // time domain (where lane packing naturally lives). When the width is unknown
  // we simply skip the gap rather than guessing.
  const gapMs = scale.widthPx > 0 ? (collisionGapPx / scale.widthPx) * totalMs : 0;

  // Bucket the original indices by depth so we can preserve input order on output.
  const indicesByDepth = new Map<number, number[]>();
  let maxDepth = 0;
  spans.forEach((span, i) => {
    const d = Math.max(0, getDepth(span));
    if (d > maxDepth) maxDepth = d;
    const bucket = indicesByDepth.get(d);
    if (bucket) bucket.push(i);
    else indicesByDepth.set(d, [i]);
  });

  const lanesByDepth: number[] = new Array(spans.length === 0 ? 0 : maxDepth + 1).fill(0);
  const laneOf = new Map<number, number>(); // span index -> lane
  let yCursor = 0;
  const depthTop: number[] = new Array(lanesByDepth.length).fill(0);

  for (let depth = 0; depth < lanesByDepth.length; depth++) {
    const indices = indicesByDepth.get(depth);
    depthTop[depth] = yCursor;
    if (!indices || indices.length === 0) continue;

    // Sort by start time, then by end time — stable, deterministic packing.
    indices.sort((a, b) => {
      const sa = getStart(spans[a]);
      const sb = getStart(spans[b]);
      if (sa !== sb) return sa - sb;
      return getEnd(spans[a]) - getEnd(spans[b]);
    });

    // First-fit lane packing: laneEnds[l] holds the time at which lane l next
    // becomes free (the previous bar's end + the collision gap).
    const laneEnds: number[] = [];
    for (const idx of indices) {
      const start = getStart(spans[idx]);
      const end = getEnd(spans[idx]);
      let placed = -1;
      for (let l = 0; l < laneEnds.length; l++) {
        if (start >= laneEnds[l]) {
          placed = l;
          break;
        }
      }
      if (placed === -1) {
        placed = laneEnds.length;
        laneEnds.push(0);
      }
      laneEnds[placed] = end + gapMs;
      laneOf.set(idx, placed);
    }

    const laneCount = Math.max(laneEnds.length, 1);
    lanesByDepth[depth] = laneCount;
    const blockHeight = laneCount * rowHeight + (laneCount - 1) * laneGap;
    yCursor += blockHeight + depthGap;
  }

  // Trim the trailing depth gap so the body hugs the last lane.
  const totalHeight = Math.max(yCursor - depthGap, spans.length ? rowHeight : 0);

  const positioned: LaidOutSpan<T>[] = spans.map((span, i) => {
    const depth = Math.max(0, getDepth(span));
    const lane = laneOf.get(i) ?? 0;
    const start = getStart(span);
    const end = getEnd(span);
    const leftPct = ((start - scale.offsetStart) / totalMs) * 100;
    const widthPct = Math.max(((end - start) / totalMs) * 100, minWidthPct);
    const top = depthTop[depth] + lane * (rowHeight + laneGap);
    return { span, depth, lane, leftPct, widthPct, top, height: rowHeight };
  });

  return { spans: positioned, totalHeight, lanesByDepth };
}
