import pytest

from redundant.runtime import Redundant
from redundant.memory_store import InMemoryStore
from redundant.schema import Decision
from redundant import tools


@pytest.fixture(autouse=True)
def reset_side_effects():
    tools.SIDE_EFFECT_LOG.sends.clear()
    yield
    tools.SIDE_EFFECT_LOG.sends.clear()


def make_runtime(run_id="run-test"):
    return Redundant(run_id=run_id, store=InMemoryStore())


def test_exact_reuse_same_call_twice():
    r = make_runtime()
    e1 = r.tool("research-agent", "search_docs", {"query": "redis caching"})
    e2 = r.tool("research-agent", "search_docs", {"query": "redis caching"})
    assert e1.decision == Decision.EXECUTE
    assert e2.decision == Decision.EXACT_REUSE
    assert e2.output == e1.output  # reused output matches
    assert e2.saved_cost_usd >= 0.0
    assert e2.actual_cost_usd == 0.0


def test_cross_agent_reuse():
    # Different agent, same run + same call -> reuse across agents.
    r = make_runtime()
    e1 = r.tool("research-agent", "scan_repo", {"topic": "vector search"})
    e2 = r.tool("report-agent", "scan_repo", {"topic": "vector search"})
    assert e1.decision == Decision.EXECUTE
    assert e2.decision == Decision.EXACT_REUSE
    assert e2.source_call_id == e1.call_id


def test_side_effecting_never_replays():
    r = make_runtime()
    e1 = r.tool("report-agent", "send_email", {"to": "a@b.com", "subject": "hi"})
    e2 = r.tool("report-agent", "send_email", {"to": "a@b.com", "subject": "hi"})
    assert e1.decision == Decision.EXECUTE
    assert e2.decision == Decision.BLOCK_OR_WARN
    # The underlying side effect ran exactly once.
    assert len(tools.SIDE_EFFECT_LOG.sends) == 1


def test_loop_detection():
    r = make_runtime()
    r.tool("research-agent", "search_docs", {"query": "loop"})
    r.tool("research-agent", "search_docs", {"query": "loop"})
    e3 = r.tool("research-agent", "search_docs", {"query": "loop"})
    assert e3.decision == Decision.BLOCK_OR_WARN
    assert "loop" in e3.explanation.lower()


def test_semantic_reuse(monkeypatch):
    # Force paraphrases to share an embedding so KNN matches deterministically.
    def fake_embed(text, settings=None):
        return [1.0, 0.0, 0.0] if "redis" in text else [0.0, 1.0, 0.0]

    monkeypatch.setattr("redundant.runtime.embed_list", fake_embed)
    r = make_runtime()
    e1 = r.tool("research-agent", "search_docs", {"query": "redis cache layer"})
    e2 = r.tool("report-agent", "search_docs", {"query": "redis caching approaches"})
    assert e1.decision == Decision.EXECUTE
    assert e2.decision == Decision.SEMANTIC_REUSE
    assert e2.verifier_score is not None and e2.verifier_score >= 0.86


def test_llm_execute_with_stub_client():
    class _Block:
        type = "text"
        text = "stubbed answer"

    class _Resp:
        content = [_Block()]

    class _Msgs:
        def create(self, **kwargs):
            return _Resp()

    class _Client:
        messages = _Msgs()

    r = Redundant(run_id="run-llm", store=InMemoryStore(), anthropic_client=_Client())
    e = r.llm("report-agent", [{"role": "user", "content": "summarize"}], model="claude-haiku-4-5")
    assert e.decision == Decision.EXECUTE
    assert e.output == "stubbed answer"
    assert e.actual_cost_usd > 0.0
