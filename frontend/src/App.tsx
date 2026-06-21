import { useEffect, useMemo, useState } from "react";
import { getFindings, listRuns } from "./api/client";
import { Flamegraph } from "./components/Flamegraph";
import { HeadlineBanner } from "./components/HeadlineBanner";
import { FindingsList } from "./components/FindingsList";
import { RootCausePanel } from "./components/RootCausePanel";
import { TopBar } from "./components/TopBar";
import { theme } from "./theme";
import type { FindingsResponse, Run } from "./types";

export function App() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRun, setSelectedRun] = useState<string>("");
  const [mode, setMode] = useState<"batch" | "replay">("batch");
  const [diagnosed, setDiagnosed] = useState(true);
  const [reran] = useState(false);
  const [data, setData] = useState<FindingsResponse | null>(null);
  const [selectedFinding, setSelectedFinding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load the run list; non-blocking — the dashboard renders whether or not it
  // resolves (the static fallback path is the safety net for both `/api/runs`
  // and `/findings`).
  useEffect(() => {
    listRuns().then((rs) => {
      setRuns(rs);
      if (rs.length && !selectedRun) setSelectedRun(rs[0].run_id);
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Load findings whenever the selected run changes.
  useEffect(() => {
    setData(null);
    setError(null);
    getFindings(selectedRun || undefined)
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [selectedRun]);

  // First finding auto-selected so the root-cause panel renders something.
  useEffect(() => {
    if (data && data.findings.length && !selectedFinding) {
      setSelectedFinding(data.findings[0].finding_id);
    }
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const selFinding = useMemo(
    () => (data ? data.findings.find((f) => f.finding_id === selectedFinding) ?? null : null),
    [data, selectedFinding]
  );

  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        background: theme.bg,
        color: theme.text,
        fontFamily: theme.sans,
        overflow: "hidden",
      }}
    >
      <TopBar
        runs={runs}
        selectedRun={selectedRun}
        onSelectRun={setSelectedRun}
        mode={mode}
        onSelectMode={setMode}
        streamLabel={mode === "replay" ? "replay" : "trace loaded"}
        streamGreen={mode !== "replay"}
      />

      <HeadlineBanner
        diagnosed={diagnosed}
        totalCost={data?.total_cost_usd ?? 0}
        wastedCost={data?.wasted_cost_usd ?? 0}
        wastePct={data?.waste_pct ?? 0}
        findingCount={data?.findings.length ?? 0}
        onToggleDiagnose={() => setDiagnosed((d) => !d)}
      />

      <div className="rdt-scroll" style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        <div style={{ maxWidth: 1480, margin: "0 auto", padding: "18px 20px 36px" }}>
          {error && !data && (
            <div
              style={{
                padding: 24,
                color: theme.redSoft,
                fontFamily: theme.mono,
                fontSize: 12,
                background: theme.surface,
                border: `1px solid ${theme.border}`,
                borderRadius: 8,
              }}
            >
              Failed to load: {error}
            </div>
          )}

          {data && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 16, alignItems: "start" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
                <Flamegraph
                  spans={data.spans}
                  findings={data.findings}
                  diagnosed={diagnosed}
                  reran={reran}
                  selectedFinding={selectedFinding}
                  onSelectFinding={setSelectedFinding}
                />
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {diagnosed && <RootCausePanel finding={selFinding} onClose={() => setSelectedFinding(null)} />}
                <FindingsList
                  findings={diagnosed ? data.findings : []}
                  selectedFinding={selectedFinding}
                  onSelect={setSelectedFinding}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
