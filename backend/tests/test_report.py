from redundant.demo import run_demo_task
from redundant.memory_store import InMemoryStore
from redundant.report import build_report
from redundant.schema import Decision


def test_report_reconciles_and_shows_savings():
    store = InMemoryStore()
    run_demo_task("run-demo", "redundant", store)
    events = store.read_events("run-demo")
    report = build_report("run-demo", events)

    # Every attempted call is accounted for.
    assert report.attempted_calls == len(events)
    assert report.attempted_calls == report.executed_calls + report.reused_or_blocked_calls

    # The scripted waste produces real reuse/blocks and dollar savings.
    assert report.reused_or_blocked_calls >= 3
    assert report.saved_cost_usd >= 0.0
    assert 0.0 <= report.redundant_rate <= 1.0
    # Baseline >= actual since saved cost is non-negative.
    assert report.estimated_baseline_cost_usd >= report.actual_cost_usd
    assert report.fixes  # fix suggestions attached


def test_baseline_mode_executes_everything():
    store = InMemoryStore()
    run_demo_task("run-base", "baseline", store)
    events = store.read_events("run-base")
    report = build_report("run-base", events)
    assert report.reused_or_blocked_calls == 0
    assert report.executed_calls == report.attempted_calls
    assert report.saved_cost_usd == 0.0


def test_side_effect_blocked_in_demo():
    store = InMemoryStore()
    run_demo_task("run-se", "redundant", store)
    events = store.read_events("run-se")
    blocks = [e for e in events if e.decision == Decision.BLOCK_OR_WARN]
    # At least the duplicated email + the looped search trip blocks.
    assert len(blocks) >= 2
