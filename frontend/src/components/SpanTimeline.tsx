import { useMemo } from "react";
import { hexA, theme } from "../theme";
import { formatDemoUsd } from "../api/displayMoney";
import { shortLabel } from "../api/modelInfo";
import type { Finding, Span } from "../types";

interface Props {
  spans: Span[];
  findings: Finding[];
  diagnosed: boolean;
  modeReplay: boolean;
  scrubVal: number | null;            // null → show all leaves
  onScrub: (n: number) => void;
  expandedSpan: string | null;
  onToggleExpand: (id: string) => void;
  selectedFinding: string | null;
  onSelectFinding: (id: string) => void;
}

const fmtTs = (ms: number, offset = 0) => ((ms - offset) / 1000).toFixed(2) + "s";

export function SpanTimeline({
  spans,
  findings,
  diagnosed,
  modeReplay,
  scrubVal,
  onScrub,
  expandedSpan,
  onToggleExpand,
  selectedFinding,
  onSelectFinding,
}: Props) {
  const offset = useMemo(() => Math.min(...spans.map((s) => s.start_time), 0), [spans]);

  const leaves = useMemo(
    () =>
      spans
        .filter((s) => s.kind !== "agent")
        .slice()
        .sort((a, b) => a.start_time - b.start_time),
    [spans]
  );

  const findingBySpan = useMemo(() => {
    const m = new Map<string, Finding>();
    for (const f of findings) for (const sid of f.span_ids) m.set(sid, f);
    return m;
  }, [findings]);

  const scrubMax = leaves.length;
  const effectiveN = modeReplay && scrubVal != null ? scrubVal : scrubMax;
  const visible = leaves.slice(0, effectiveN);

  return (
    <div style={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 8 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "13px 17px",
          borderBottom: `1px solid ${theme.border}`,
        }}
      >
        <span
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.09em",
            color: "var(--gt-sec)",
            fontWeight: 600,
          }}
        >
          Span Timeline
        </span>
        <span style={{ fontFamily: theme.mono, fontSize: 11, color: "var(--gt-dimmer)" }}>{leaves.length} calls</span>
        <span style={{ flex: 1 }} />
        {modeReplay && (
          <span style={{ fontFamily: theme.mono, fontSize: 10, color: theme.amber }}>
            replay {effectiveN} / {scrubMax}
          </span>
        )}
      </div>

      <div>
        {visible.map((sp) => {
          const finding = diagnosed ? findingBySpan.get(sp.span_id) ?? null : null;
          const badge = badgeFor(finding);
          const agentColor = theme.agents[sp.agent_name] || "var(--gt-mut)";
          const expanded = expandedSpan === sp.span_id;
          const hash = sp.input_hash || sp.span_id.slice(2);
          return (
            <div key={sp.span_id} style={{ borderBottom: `1px solid ${theme.borderInner}` }}>
              <div
                onClick={() => {
                  onToggleExpand(sp.span_id);
                  if (finding) onSelectFinding(finding.finding_id);
                }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 9,
                  padding: "8px 17px",
                  cursor: "pointer",
                  background: expanded ? "#13181E" : "transparent",
                }}
              >
                <span
                  style={{
                    fontFamily: theme.mono,
                    fontSize: 9,
                    color: "var(--gt-dim)",
                    transform: expanded ? "rotate(90deg)" : "none",
                    transition: "transform 0.15s",
                    display: "inline-block",
                    flex: "0 0 9px",
                    textAlign: "center",
                  }}
                >
                  ▸
                </span>
                <span
                  style={{
                    fontFamily: theme.mono,
                    fontSize: 11,
                    color: "var(--gt-dimmer)",
                    fontVariantNumeric: "tabular-nums",
                    flex: "0 0 50px",
                  }}
                >
                  {fmtTs(sp.start_time, offset)}
                </span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 5, flex: "0 0 auto" }}>
                  <span
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: "50%",
                      background: agentColor,
                      display: "inline-block",
                      flex: "0 0 auto",
                    }}
                  />
                  <span style={{ fontFamily: theme.mono, fontSize: 11, color: "var(--gt-sec)" }}>{sp.agent_name}</span>
                </span>
                <span
                  style={{
                    fontFamily: theme.mono,
                    fontSize: 9,
                    fontWeight: 600,
                    letterSpacing: "0.04em",
                    color: badge.color,
                    background: hexA(badge.color.startsWith("#") ? badge.color : "#8C95A2", 0.12),
                    border: `1px solid ${hexA(badge.color.startsWith("#") ? badge.color : "#8C95A2", 0.26)}`,
                    padding: "2px 6px",
                    borderRadius: 4,
                    whiteSpace: "nowrap",
                    flex: "0 0 auto",
                  }}
                >
                  {badge.text}
                </span>
                <span
                  style={{
                    fontFamily: theme.mono,
                    fontSize: 12,
                    color: theme.text,
                    minWidth: 0,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {sp.name.replace("tool:", "").replace("llm:", "")}
                  <span style={{ color: "var(--gt-dim)" }}> · {sp.input}</span>
                </span>
                <span style={{ flex: 1 }} />
                <span
                  style={{
                    fontFamily: theme.mono,
                    fontSize: 11,
                    color: "var(--gt-dim)",
                    fontVariantNumeric: "tabular-nums",
                    flex: "0 0 auto",
                  }}
                >
                  {formatDemoUsd(sp.cost_usd)}
                </span>
              </div>

              {expanded && (
                <div style={{ padding: "3px 17px 14px 50px", background: theme.surfaceDeep }}>
                  <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginBottom: 11 }}>
                    {[
                      ["model", shortLabel(sp.model)],
                      ["tok", `${sp.tokens.input}→${sp.tokens.output}`],
                      ["dur", `${((sp.end_time - sp.start_time) / 1000).toFixed(2)}s`],
                      ["cost", formatDemoUsd(sp.cost_usd)],
                      ["hash", hash],
                    ].map(([label, val]) => (
                      <span
                        key={label}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                          fontFamily: theme.mono,
                          fontSize: 10.5,
                          padding: "3px 8px",
                          background: theme.bg,
                          border: `1px solid #232A33`,
                          borderRadius: 5,
                        }}
                      >
                        <span style={{ color: "var(--gt-dim)", textTransform: "uppercase", letterSpacing: "0.03em" }}>
                          {label}
                        </span>
                        <span style={{ color: theme.textSoft }}>{val}</span>
                      </span>
                    ))}
                  </div>
                  <DetailRow label="in" value={sp.input} />
                  <DetailRow label="out" value={sp.output} />
                  {finding && (
                    <div
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectFinding(finding.finding_id);
                      }}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        marginTop: 10,
                        padding: "8px 10px",
                        background: theme.bg,
                        border: `1px solid #232A33`,
                        borderRadius: 6,
                        cursor: "pointer",
                      }}
                    >
                      <span
                        style={{
                          width: 7,
                          height: 7,
                          borderRadius: 2,
                          background: hexA(badge.color, 0.4),
                          border: `1px solid ${hexA(badge.color, 0.7)}`,
                          display: "inline-block",
                          flex: "0 0 auto",
                        }}
                      />
                      <span style={{ fontSize: 11, color: theme.textSoft }}>
                        part of <span style={{ color: theme.text, fontWeight: 500 }}>{finding.description.split(" ").slice(0, 4).join(" ")}…</span> ·{" "}
                        {finding.route === "alert" ? "⚠ Sentry" : "⤴ LangCache"}
                      </span>
                      <span style={{ flex: 1 }} />
                      <span style={{ fontFamily: theme.mono, fontSize: 10, color: "var(--gt-dim)" }}>focus →</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {modeReplay && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "11px 17px",
            borderTop: `1px solid ${theme.border}`,
          }}
        >
          <span style={{ fontFamily: theme.mono, fontSize: 10, color: "var(--gt-dim)" }}>SCRUB</span>
          <input
            type="range"
            min={1}
            max={scrubMax}
            value={effectiveN}
            onChange={(e) => onScrub(parseInt(e.target.value, 10))}
            style={{ flex: 1, accentColor: theme.amber }}
          />
          <span
            style={{
              fontFamily: theme.mono,
              fontSize: 11,
              color: "var(--gt-sec)",
              minWidth: 54,
              textAlign: "right",
            }}
          >
            {effectiveN} / {scrubMax}
          </span>
        </div>
      )}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", gap: 9, marginBottom: 6 }}>
      <span style={{ fontFamily: theme.mono, fontSize: 10, color: "var(--gt-dim)", flex: "0 0 28px", paddingTop: 2 }}>{label}</span>
      <span style={{ fontFamily: theme.mono, fontSize: 11.5, color: "#C5CCD5", lineHeight: 1.5 }}>{value}</span>
    </div>
  );
}

function badgeFor(finding: Finding | null): { text: string; color: string } {
  if (!finding) return { text: "OK", color: "#8C95A2" };
  if (finding.type === "repetition") return { text: "REDUNDANT", color: theme.red };
  if (finding.type === "semantic_duplicate") return { text: "SEMANTIC_DUP", color: theme.amber };
  return { text: "RUNAWAY", color: theme.red };
}
