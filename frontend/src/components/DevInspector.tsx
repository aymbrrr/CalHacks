import { useEffect, useState } from "react";
import { hexA, theme } from "../theme";
import { getAlerts } from "../api/client";
import type { AlertsResponse, Finding, Span } from "../types";

interface Props {
  runId: string;
  spans: Span[];
  findings: Finding[];
}

type TabKey = "streams" | "cache" | "sentry" | "terac" | "band";

const TAB_LABELS: [TabKey, string][] = [
  ["streams", "Redis Streams"],
  ["cache", "Redis LangCache"],
  ["sentry", "Sentry"],
  ["terac", "Terac"],
  ["band", "Band"],
];

const STUB: Record<Exclude<TabKey, "streams" | "sentry">, { title: string; body: string }> = {
  cache: {
    title: "LangCache — key (tool_name, input_hash)",
    body:
      "Wasteful findings write here after the read-only allowlist gate; reads are served only on exact input_hash match within TTL. The cache-routed findings round-trip through this key on Re-run, dropping the total.",
  },
  terac: {
    title: "Terac — verifier eval",
    body:
      "Terac's human-labeled call-pair dataset validates the verifier's reuse decisions on held-out examples. Semantic-duplicate findings are only cached if the verifier clears them against this ground truth.",
  },
  band: {
    title: "Band — agent collaboration",
    body:
      "Band runs the agent team and emits one span per call to Redis Streams. Every pathology Redundant detects originates from this multi-agent run.",
  },
};

export function DevInspector({ runId, spans, findings }: Props) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<TabKey>("streams");
  const [alerts, setAlerts] = useState<AlertsResponse | null>(null);

  useEffect(() => {
    if (open && tab === "sentry" && !alerts) {
      getAlerts().then(setAlerts);
    }
  }, [open, tab, alerts]);

  return (
    <div
      style={{
        background: theme.surface,
        border: `1px solid ${theme.border}`,
        borderRadius: 8,
        overflow: "hidden",
        marginTop: 16,
      }}
    >
      <div
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "13px 17px",
          cursor: "pointer",
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
          Dev Inspector
        </span>
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: theme.mono,
            fontSize: 12,
            color: "var(--gt-dim)",
            transform: open ? "rotate(180deg)" : "none",
            display: "inline-block",
            transition: "transform 0.18s",
          }}
        >
          ▾
        </span>
      </div>

      {open && (
        <div style={{ borderTop: `1px solid ${theme.border}` }}>
          <div style={{ display: "flex", gap: 2, padding: "8px 13px", borderBottom: `1px solid ${theme.border}` }}>
            {TAB_LABELS.map(([k, label]) => {
              const active = tab === k;
              return (
                <div
                  key={k}
                  onClick={() => setTab(k)}
                  style={{
                    padding: "6px 11px",
                    borderRadius: 5,
                    fontFamily: theme.mono,
                    fontSize: 11,
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                    color: active ? theme.text : "var(--gt-dim)",
                    background: active ? "#1A1F26" : "transparent",
                    border: `1px solid ${active ? theme.border : "transparent"}`,
                  }}
                >
                  {label}
                </div>
              );
            })}
          </div>

          {tab === "streams" && <StreamsTab runId={runId} spans={spans} findings={findings} />}
          {tab === "sentry" && <SentryTab alerts={alerts} />}
          {tab !== "streams" && tab !== "sentry" && (
            <StubPanel title={STUB[tab as Exclude<TabKey, "streams" | "sentry">].title} body={STUB[tab as Exclude<TabKey, "streams" | "sentry">].body} />
          )}
        </div>
      )}
    </div>
  );
}

function StreamsTab({ runId, spans, findings }: { runId: string; spans: Span[]; findings: Finding[] }) {
  const findingBySpan = new Map<string, Finding>();
  for (const f of findings) for (const sid of f.span_ids) findingBySpan.set(sid, f);

  const leaves = spans
    .filter((s) => s.kind !== "agent")
    .slice()
    .sort((a, b) => a.start_time - b.start_time);

  return (
    <div
      className="rdt-scroll"
      style={{
        maxHeight: 240,
        overflowY: "auto",
        padding: "12px 17px",
        fontFamily: theme.mono,
        fontSize: 11,
        lineHeight: 1.7,
        background: theme.bg,
      }}
    >
      <div style={{ fontSize: 10, color: "var(--gt-dim)", marginBottom: 8 }}>
        XRANGE trace:{runId || "run-default"} - +  —  one entry per span, read-only
      </div>
      {leaves.map((sp, i) => {
        const finding = findingBySpan.get(sp.span_id);
        const color = finding
          ? finding.type === "semantic_duplicate"
            ? theme.amber
            : theme.red
          : theme.text;
        const obj = {
          span_id: sp.span_id,
          parent: sp.parent_span_id,
          agent: sp.agent_name,
          tool_name: sp.tool_name || sp.name.replace("llm:", "").replace("tool:", ""),
          input_hash: sp.input_hash,
          tokens: { in: sp.tokens.input, out: sp.tokens.output },
          model: sp.model,
        };
        return (
          <div key={sp.span_id} style={{ whiteSpace: "pre-wrap", padding: "1px 0" }}>
            <span style={{ color: "var(--gt-dimmer)" }}>{String(i + 1).padStart(2, "0")}</span>{" "}
            <span style={{ color: hexA(color.startsWith("#") ? color : "#9AA3B0", 0.95) }}>
              {JSON.stringify(obj)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function SentryTab({ alerts }: { alerts: AlertsResponse | null }) {
  if (!alerts) {
    return (
      <div style={{ padding: "20px 17px", background: theme.bg }}>
        <div style={{ fontFamily: theme.mono, fontSize: 11, color: "var(--gt-dim)" }}>loading /alerts…</div>
      </div>
    );
  }
  return (
    <div style={{ padding: "16px 17px", background: theme.bg }}>
      <div style={{ display: "flex", gap: 9, alignItems: "center", marginBottom: 12 }}>
        <span
          style={{
            fontFamily: theme.mono,
            fontSize: 9.5,
            fontWeight: 600,
            letterSpacing: "0.05em",
            color: alerts.mock ? theme.amber : theme.green,
            background: hexA(alerts.mock ? "#F59E0B" : "#4ADE80", 0.13),
            border: `1px solid ${hexA(alerts.mock ? "#F59E0B" : "#4ADE80", 0.3)}`,
            padding: "2px 7px",
            borderRadius: 4,
          }}
        >
          {alerts.mock ? "MOCK MODE" : "LIVE"}
        </span>
        <span style={{ fontSize: 12, color: "var(--gt-sec)" }}>
          {alerts.events.length} incident{alerts.events.length === 1 ? "" : "s"}
        </span>
      </div>
      {alerts.events.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--gt-dim)", lineHeight: 1.5 }}>
          No alerts fired. Runaway findings route here when count ≥ R_max and convergence = none.
        </div>
      ) : (
        <div className="rdt-scroll" style={{ maxHeight: 200, overflowY: "auto" }}>
          {alerts.events.map((ev, i) => (
            <div
              key={i}
              style={{
                fontFamily: theme.mono,
                fontSize: 11,
                lineHeight: 1.6,
                color: theme.redSoft,
                padding: "6px 9px",
                marginBottom: 6,
                background: "#160F11",
                border: "1px solid rgba(248,113,113,0.32)",
                borderRadius: 5,
              }}
            >
              {ev.message || ev.type || JSON.stringify(ev)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StubPanel({ title, body }: { title: string; body: string }) {
  return (
    <div style={{ padding: "30px 17px", background: theme.bg }}>
      <div style={{ fontFamily: theme.mono, fontSize: 12, color: theme.text, marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 12, color: "var(--gt-sec)", lineHeight: 1.5, maxWidth: 560 }}>{body}</div>
    </div>
  );
}
