from redundant.schema import (
    CallRecord,
    RedundantEvent,
    Run,
    RunReport,
    DuplicateCluster,
    SuggestedFix,
)


def test_callrecord_roundtrip_keys():
    rec = CallRecord(
        call_id="c1", run_id="r1", agent_id="research-agent", call_type="tool",
        tool_name="search_docs", cacheability="pure", normalized_input="...",
        input_hash="deadbeef", created_at="2026-06-20T00:00:00Z",
    )
    d = rec.model_dump(mode="json")
    expected = {
        "call_id", "run_id", "agent_id", "call_type", "tool_name", "cacheability",
        "normalized_input", "input_hash", "embedding", "output", "input_tokens",
        "output_tokens", "cost_usd", "latency_ms", "created_at", "state_fingerprint",
        "decision", "reuse_source_call_id", "verifier_score", "explanation",
    }
    assert set(d.keys()) == expected
    assert CallRecord(**d).call_id == "c1"


def test_event_contract_keys():
    ev = RedundantEvent(
        event_id="0-1", run_id="r1", ts="2026-06-20T00:00:00Z", agent_id="report-agent",
        call_id="c2", call_type="llm", tool_name="llm", decision="EXACT_REUSE",
        cacheability="pure", summary="reused", explanation="exact hit",
    )
    d = ev.model_dump(mode="json")
    assert d["decision"] == "EXACT_REUSE"
    assert d["sponsor_hooks"] == []
    assert RedundantEvent(**d).call_id == "c2"


def test_report_and_nested_models():
    rep = RunReport(
        run_id="r1", attempted_calls=10, executed_calls=4, reused_or_blocked_calls=6,
        redundant_rate=0.6, estimated_baseline_cost_usd=1.0, actual_cost_usd=0.4,
        saved_cost_usd=0.6, saved_latency_ms=9000, saved_tokens=4200,
        clusters=[DuplicateCluster(cluster_id="cl1", label="web search", calls=5,
                                   unique_needed=1, waste_percent=80.0, saved_cost_usd=0.4,
                                   saved_latency_ms=6000, agent_ids=["research-agent"])],
        fixes=[SuggestedFix(fix_id="f1", title="cache it", description="add ttl")],
    )
    d = rep.model_dump(mode="json")
    assert d["clusters"][0]["waste_percent"] == 80.0
    assert RunReport(**d).redundant_rate == 0.6


def test_run_model():
    run = Run(run_id="r1", task="t", mode="redundant", status="running",
              started_at="2026-06-20T00:00:00Z")
    assert run.completed_at is None
