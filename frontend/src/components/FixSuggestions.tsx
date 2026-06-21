import { useState } from "react";
import { hexA, theme } from "../theme";
import type { SuggestedFix } from "../types";

interface Props {
  fixes: SuggestedFix[];
}

interface SponsorSpec {
  mono: string;
  name: string;
  color: string;
}

function specFor(hook?: string | null): SponsorSpec {
  const h = (hook || "").toLowerCase();
  if (h.includes("redis")) return { mono: "R", name: "Redis LangCache", color: theme.sponsors.redis };
  if (h.includes("anthropic")) return { mono: "A", name: "Anthropic", color: theme.sponsors.anthropic };
  if (h.includes("token")) return { mono: "TC", name: "The Token Company", color: theme.sponsors.tokenco };
  if (h.includes("terac")) return { mono: "T", name: "Terac", color: theme.sponsors.terac };
  return { mono: "·", name: hook || "Sponsor", color: theme.text };
}

export function FixSuggestions({ fixes }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(fixes[0]?.fix_id ?? null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const copy = (fix: SuggestedFix) => {
    if (!fix.code_hint) return;
    try {
      navigator.clipboard?.writeText(fix.code_hint);
    } catch {
      // clipboard unavailable; degrade silently
    }
    setCopiedId(fix.fix_id);
    window.setTimeout(() => setCopiedId((id) => (id === fix.fix_id ? null : id)), 1100);
  };

  if (!fixes.length) return null;

  return (
    <div style={{ background: theme.surface, border: `1px solid ${theme.border}`, borderRadius: 8, padding: "14px 16px" }}>
      <div
        style={{
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.09em",
          color: "var(--gt-sec)",
          fontWeight: 600,
          marginBottom: 13,
        }}
      >
        Fix Suggestions
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        {fixes.map((f) => {
          const sp = specFor(f.sponsor_hook);
          const expanded = expandedId === f.fix_id;
          const copied = copiedId === f.fix_id;
          return (
            <div
              key={f.fix_id}
              style={{
                border: `1px solid ${expanded ? theme.text : theme.border}`,
                borderRadius: 6,
                overflow: "hidden",
                background: theme.surfaceAlt,
              }}
            >
              <div
                onClick={() => setExpandedId((id) => (id === f.fix_id ? null : f.fix_id))}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 9,
                  padding: "10px 12px",
                  cursor: "pointer",
                }}
              >
                <span
                  style={{
                    fontFamily: theme.mono,
                    fontSize: 10,
                    color: theme.green,
                    transform: expanded ? "rotate(90deg)" : "none",
                    display: "inline-block",
                    transition: "transform 0.15s",
                  }}
                >
                  ▸
                </span>
                <span
                  title={sp.name}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    minWidth: 17,
                    height: 17,
                    padding: "0 4px",
                    borderRadius: 4,
                    background: hexA(sp.color, 0.18),
                    border: `1px solid ${hexA(sp.color, 0.32)}`,
                    color: sp.color,
                    fontFamily: theme.mono,
                    fontSize: 8,
                    fontWeight: 600,
                  }}
                >
                  {sp.mono}
                </span>
                <span style={{ flex: 1, fontSize: 12, color: theme.text, lineHeight: 1.35 }}>{f.title}</span>
              </div>
              {expanded && (
                <div style={{ padding: "0 12px 12px 32px" }}>
                  <div style={{ fontSize: 11, color: "var(--gt-sec)", lineHeight: 1.5, marginBottom: 9 }}>
                    {f.description}
                  </div>
                  {f.code_hint && (
                    <div
                      style={{
                        position: "relative",
                        background: theme.bg,
                        border: `1px solid ${theme.border}`,
                        borderRadius: 5,
                        padding: "10px 12px",
                      }}
                    >
                      <div
                        onClick={(e) => {
                          e.stopPropagation();
                          copy(f);
                        }}
                        style={{
                          position: "absolute",
                          top: 7,
                          right: 8,
                          fontFamily: theme.mono,
                          fontSize: 9.5,
                          color: copied ? theme.green : "var(--gt-dim)",
                          border: `1px solid ${theme.border}`,
                          borderRadius: 4,
                          padding: "2px 6px",
                          cursor: "pointer",
                          background: theme.bg,
                        }}
                      >
                        {copied ? "copied" : "copy"}
                      </div>
                      <pre
                        style={{
                          margin: 0,
                          fontFamily: theme.mono,
                          fontSize: 11,
                          lineHeight: 1.6,
                          color: theme.greenSoft,
                          whiteSpace: "pre-wrap",
                        }}
                      >
                        {f.code_hint}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
