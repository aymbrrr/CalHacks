from redundant.estimate import (
    count_tokens,
    count_message_tokens,
    estimate_cost,
    savings_from_reuse,
)


def test_count_tokens_heuristic():
    assert count_tokens("") == 0
    assert count_tokens("abcd") == 1
    assert count_tokens("a" * 400) == 100


def test_count_message_tokens():
    msgs = [
        {"role": "user", "content": "a" * 400},
        {"role": "assistant", "content": "a" * 800},
    ]
    assert count_message_tokens(msgs) == 300


def test_estimate_cost_known_model():
    # haiku: $0.80/Mtok in, $4.0/Mtok out.
    cost = estimate_cost("claude-haiku-4-5", 1_000_000, 1_000_000)
    assert cost == round(0.80 + 4.0, 6)


def test_estimate_cost_unknown_model_falls_back():
    cost = estimate_cost("some-future-model", 1_000_000, 0)
    # falls back to sonnet input pricing ($3/Mtok).
    assert cost == 3.0


def test_savings_from_reuse():
    s = savings_from_reuse(0.018, 2200, 1500)
    assert s == {"saved_cost_usd": 0.018, "saved_latency_ms": 2200, "saved_tokens": 1500}
