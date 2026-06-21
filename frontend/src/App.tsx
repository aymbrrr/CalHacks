import { useEffect, useMemo, useRef, useState } from "react";
import { getFindings, getReport, listRuns, rerun, startRun, streamRun } from "./api/client";
import { DevInspector } from "./components/DevInspector";
import { Flamegraph } from "./components/Flamegraph";
import { HeadlineBanner } from "./components/HeadlineBanner";
import { FindingsList } from "./components/FindingsList";
import { FixSuggestions } from "./components/FixSuggestions";
import { RerunBar } from "./components/RerunBar";
import { RootCausePanel } from "./components/RootCausePanel";
import { SpanTimeline } from "./components/SpanTimeline";
import { TopBar } from "./components/TopBar";
import { theme } from "./theme";
import type { FindingsResponse, RerunResponse, Run, RunReport } from "./types";

export function App() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRun, setSelectedRun] = useState<string>("");
  const [mode, setMode] = useState<"batch" | "replay">("batch");
  const [diagnosed, setDiagnosed] = useState(true);
  const [reran, setReran] = useState(false);
  const [rerunData, setRerunData] = useState<RerunResponse | null>(null);
  const [data, setData] = useState<FindingsResponse | null>(null);
  const [report, setReport] = useState<RunReport | null>(null);
  const [selectedFinding, setSelectedFinding] = useState<string | null>(null);
  const [expandedSpan, setExpandedSpan] = useState<string | null>(null);
  const [scrubVal, setScrubVal] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<string>("idle");
  const [liveEventCount, setLiveEventCount] = useState<number>(0);
  const [loading, setLoading] = useState(false);

  // Monotonic request id for findings/report fetches. A stale response (older
  // request, newer selectedRun) will see its id mismatch the current one and
  // get dropped instead of overwriting fresh state.
  const fetchSeq = useRef(0);

  // Load the run list; non-blocking — the dashboard renders whether or not it
  // resolves (the static fallback path is the safety net for both `/api/runs`
  // and `/findings`).
  useEffect(() => {
    listRuns().then((rs) => {
      setRuns(rs);
      if (rs.length && !selectedRun) setSelectedRun(rs[0].run_id);
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Load findings + report whenever the selected run changes.
  //
  // Bug history: this effect used to setData(null) synchronously, which caused
  // the body to unmount and reappear as a blank screen whenever selectedRun
  // changed (most visibly: after listRuns resolves on mount). Stale data is
  // strictly better than no data — the new payload overwrites when it arrives.
  useEffect(() => {
    const seq = ++fetchSeq.current;
    setError(null);
    setLoading(true);

    getFindings(selectedRun || undefined)
      .then((d) => {
        if (seq !== fetchSeq.current) return; // stale response, drop it
        setData(d);
        setReran(false);
        setRerunData(null);
        setScrubVal(null);
        setExpandedSpan(null);
      })
      .catch((e) => {
        if (seq !== fetchSeq.current) return;
        setError(String(e));
      })
      .finally(() => {
        if (seq === fetchSeq.current) setLoading(false);
      });

    getReport(selectedRun).then((r) => {
      if (seq !== fetchSeq.current) return;
      setReport(r);
    });
  }, [selectedRun]);

  // Reset scrub when toggling between batch and replay so the bar shows "all"
  // by default whenever the user enters replay mode.
  useEffect(() => {
    setScrubVal(null);
  }, [mode]);

  const handleStartRun = async () => {
    try {
      setRunStatus("running");
      setLiveEventCount(0);
      const newRun = await startRun("Band multi-agent demo", "band");
      setRuns((prev) => [newRun, ...prev]);
      setSelectedRun(newRun.run_id);
      const cleanup = streamRun(
        newRun.run_id,
        () => setLiveEventCount((n) => n + 1),
        (completedRun) => {
          setRunStatus(completedRun.status);
          getFindings(completedRun.run_id).then(setData).catch(() => {});
          getReport(completedRun.run_id).then(setReport).catch(() => {});
          cleanup();
        }
      );
    } catch {
      setRunStatus("failed");
    }
  };

  const onRerun = async () => {
    if (!data) return;
    const result = await rerun(selectedRun, data);
    setRerunData(result);
    setReran(true);
    setDiagnosed(true);
  };

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

  // Replay mode: hide spans whose start_time is past the cutoff implied by the
  // scrub. The scrub counts leaf calls; we map it to a wall-clock cutoff so
  // both the flamegraph and the timeline reveal in lockstep.
  const replayCutoffTs = useMemo(() => {
    if (!data || mode !== "replay") return Infinity;
    const leaves = data.spans
      .filter((s) => s.kind !== "agent")
      .slice()
      .sort((a, b) => a.start_time - b.start_time);
    if (!leaves.length) return Infinity;
    const n = scrubVal ?? leaves.length;
    const idx = Math.max(0, Math.min(n - 1, leaves.length - 1));
    return leaves[idx].end_time;
  }, [data, mode, scrubVal]);

  const visibleSpans = useMemo(() => {
    if (!data) return [];
    if (mode !== "replay") return data.spans;
    return data.spans.filter((s) => s.start_time <= replayCutoffTs + 1);
  }, [data, mode, replayCutoffTs]);

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
        streamLabel={
          runStatus === "running"
            ? `live · ${liveEventCount} events`
            : loading
            ? "loading…"
            : mode === "replay"
            ? "replay"
            : "trace loaded"
        }
        streamGreen={runStatus === "running" || (!loading && mode !== "replay")}
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

          {!error && !data && (
            <div
              style={{
                padding: 24,
                color: "var(--gt-dim)",
                fontFamily: theme.mono,
                fontSize: 12,
                background: theme.surface,
                border: `1px solid ${theme.border}`,
                borderRadius: 8,
              }}
            >
              {loading ? "loading findings…" : "no data — pick a run from the selector above"}
            </div>
          )}

          {data && (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 16, alignItems: "start" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
                  <Flamegraph
                    spans={visibleSpans}
                    findings={data.findings}
                    diagnosed={diagnosed}
                    reran={reran}
                    selectedFinding={selectedFinding}
                    onSelectFinding={setSelectedFinding}
                  />
                  <RerunBar
                    reran={reran}
                    rerunData={rerunData}
                    originalCost={data.total_cost_usd}
                    onRerun={onRerun}
                  />
                  <SpanTimeline
                    spans={data.spans}
                    findings={data.findings}
                    diagnosed={diagnosed}
                    modeReplay={mode === "replay"}
                    scrubVal={scrubVal}
                    onScrub={setScrubVal}
                    expandedSpan={expandedSpan}
                    onToggleExpand={(id) =>
                      setExpandedSpan((prev) => (prev === id ? null : id))
                    }
                    selectedFinding={selectedFinding}
                    onSelectFinding={setSelectedFinding}
                  />
                  <DevInspector runId={selectedRun} spans={data.spans} findings={data.findings} />
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                  {diagnosed && <RootCausePanel finding={selFinding} onClose={() => setSelectedFinding(null)} />}
                  <FindingsList
                    findings={diagnosed ? data.findings : []}
                    selectedFinding={selectedFinding}
                    onSelect={setSelectedFinding}
                  />
                  {report && <FixSuggestions fixes={report.fixes} />}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
