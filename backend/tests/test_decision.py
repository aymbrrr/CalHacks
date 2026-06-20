from redundant.decision import decide, DecisionInput
from redundant.schema import Decision
from redundant.verifier import Candidate


def _cand(sim, cacheability="pure", call_id="src-1"):
    return Candidate(call_id=call_id, cacheability=cacheability, similarity=sim,
                     output="cached", normalized_input="...")


def test_execute_on_clean_miss():
    r = decide(DecisionInput(cacheability="pure", input_tokens=100))
    assert r.decision == Decision.EXECUTE


def test_exact_reuse():
    r = decide(DecisionInput(cacheability="pure", input_tokens=100, exact_hit_call_id="src-1"))
    assert r.decision == Decision.EXACT_REUSE
    assert r.source_call_id == "src-1"


def test_cross_agent_exact_reuse_is_scope_based():
    # The engine doesn't see agent_id at all; an exact hit reuses regardless of
    # which agent produced it. (Scope is built run-wide in normalize.scope_key.)
    r = decide(DecisionInput(cacheability="pure", input_tokens=10, exact_hit_call_id="research-call"))
    assert r.decision == Decision.EXACT_REUSE
    assert r.source_call_id == "research-call"


def test_semantic_reuse_approved():
    r = decide(DecisionInput(cacheability="pure", input_tokens=100,
                             semantic_candidates=[_cand(0.92)]))
    assert r.decision == Decision.SEMANTIC_REUSE
    assert r.verifier_score == 0.92


def test_semantic_below_threshold_executes():
    r = decide(DecisionInput(cacheability="pure", input_tokens=100,
                             semantic_candidates=[_cand(0.70)]))
    assert r.decision == Decision.EXECUTE
    assert r.source_call_id == "src-1"  # remembered why we didn't reuse


def test_unsafe_but_bloated_compresses():
    r = decide(DecisionInput(cacheability="pure", input_tokens=5000,
                             semantic_candidates=[_cand(0.70)]))
    assert r.decision == Decision.COMPRESS_AND_EXECUTE


def test_no_candidate_but_bloated_compresses():
    r = decide(DecisionInput(cacheability="pure", input_tokens=5000))
    assert r.decision == Decision.COMPRESS_AND_EXECUTE


def test_side_effecting_never_reuses_even_on_exact():
    r = decide(DecisionInput(cacheability="side_effecting", input_tokens=10,
                             exact_hit_call_id="prev-send"))
    assert r.decision == Decision.BLOCK_OR_WARN
    assert "replay" in r.explanation.lower()


def test_side_effecting_first_time_executes():
    r = decide(DecisionInput(cacheability="side_effecting", input_tokens=10))
    assert r.decision == Decision.EXECUTE


def test_state_bound_semantic_blocked_by_verifier():
    # High similarity but state_bound -> verifier rejects -> not semantic reuse.
    r = decide(DecisionInput(cacheability="state_bound", input_tokens=10,
                             semantic_candidates=[_cand(0.99, "state_bound")]))
    assert r.decision == Decision.EXECUTE


def test_loop_detection_blocks():
    r = decide(DecisionInput(cacheability="pure", input_tokens=10, hash_attempt_count=3))
    assert r.decision == Decision.BLOCK_OR_WARN
    assert "loop" in r.explanation.lower()


def test_freshness_sensitive_requires_higher_bar():
    # 0.90 clears the pure threshold (0.86) but not the freshness bar.
    r = decide(DecisionInput(cacheability="freshness_sensitive", input_tokens=10,
                             semantic_candidates=[_cand(0.90, "freshness_sensitive")]))
    assert r.decision == Decision.EXECUTE
