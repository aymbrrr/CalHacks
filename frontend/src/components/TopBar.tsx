import { theme } from "../theme";
import type { Run } from "../types";

interface Props {
  runs: Run[];
  selectedRun: string;
  onSelectRun: (id: string) => void;
  mode: "batch" | "replay";
  onSelectMode: (m: "batch" | "replay") => void;
  streamLabel: string;
  streamGreen: boolean;
}

const selectStyle: React.CSSProperties = {
  fontFamily: theme.mono,
  fontSize: 12,
  color: theme.text,
  background: theme.surface,
  border: `1px solid ${theme.border}`,
  borderRadius: 6,
  padding: "5px 26px 5px 10px",
  cursor: "pointer",
  outline: "none",
  appearance: "none",
  WebkitAppearance: "none",
  backgroundImage:
    "url(\"data:image/svg+xml,%3Csvg width='8' height='5' viewBox='0 0 8 5' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1l3 3 3-3' stroke='%236B7480' stroke-width='1.3' fill='none'/%3E%3C/svg%3E\")",
  backgroundRepeat: "no-repeat",
  backgroundPosition: "right 10px center",
};

export function TopBar({ runs, selectedRun, onSelectRun, mode, onSelectMode, streamLabel, streamGreen }: Props) {
  return (
    <div
      style={{
        height: 48,
        flex: "0 0 48px",
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "0 18px",
        borderBottom: `1px solid ${theme.border}`,
        background: theme.bg,
        position: "relative",
        zIndex: 5,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Logo />
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontFamily: theme.mono, fontSize: 15, fontWeight: 600, letterSpacing: "0.14em", lineHeight: 1 }}>
            REDUNDANT
          </span>
          <span style={{ fontSize: 10, color: "var(--gt-dim)", letterSpacing: "0.07em", lineHeight: 1, textTransform: "uppercase" }}>
            the ai cost firewall
          </span>
        </div>
      </div>
      <div style={{ flex: 1 }} />
      <span style={{ fontSize: 11, color: "var(--gt-dim)" }}>run</span>
      <select style={selectStyle} value={selectedRun} onChange={(e) => onSelectRun(e.target.value)}>
        {runs.length === 0 && <option value={selectedRun}>{selectedRun || "—"}</option>}
        {runs.map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {r.run_id} · {r.mode}
          </option>
        ))}
      </select>
      <select style={selectStyle} value={mode} onChange={(e) => onSelectMode(e.target.value as "batch" | "replay")}>
        <option value="batch">mode: batch</option>
        <option value="replay">mode: replay</option>
      </select>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 7,
          padding: "0 4px 0 12px",
          borderLeft: `1px solid ${theme.border}`,
          marginLeft: 4,
        }}
      >
        <span
          className="rdt-pulse"
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: streamGreen ? theme.green : theme.amber,
            display: "inline-block",
          }}
        />
        <span style={{ fontFamily: theme.mono, fontSize: 11, color: "var(--gt-dim)" }}>{streamLabel}</span>
      </div>
    </div>
  );
}

function Logo() {
  return (
    <svg width="27" height="20" viewBox="0 0 24 18" fill="none" aria-hidden>
      <path d="M4 3 L10 9 L4 15" stroke={theme.text} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M11 3 L17 9 L11 15" stroke={theme.green} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
