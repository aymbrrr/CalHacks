from redundant.normalize import (
    normalize_tool_args,
    normalize_messages,
    compute_hash,
    scope_key,
)


def test_reordered_args_hash_equal():
    a = normalize_tool_args("search_docs", {"query": "redis cache", "limit": 5})
    b = normalize_tool_args("search_docs", {"limit": 5, "query": "redis cache"})
    assert a == b


def test_casing_and_whitespace_collapse():
    a = normalize_tool_args("search_docs", {"query": "  Redis   Cache "})
    b = normalize_tool_args("search_docs", {"query": "redis cache"})
    assert a == b


def test_volatile_keys_dropped():
    a = normalize_tool_args("search_docs", {"query": "x", "timestamp": 1, "request_id": "abc"})
    b = normalize_tool_args("search_docs", {"query": "x"})
    assert a == b


def test_different_args_differ():
    a = normalize_tool_args("search_docs", {"query": "redis"})
    b = normalize_tool_args("search_docs", {"query": "sentry"})
    assert a != b


def test_tool_name_part_of_identity():
    a = normalize_tool_args("search_docs", {"query": "x"})
    b = normalize_tool_args("scan_repo", {"query": "x"})
    assert a != b


def test_messages_model_matters():
    msgs = [{"role": "user", "content": "hello"}]
    assert normalize_messages(msgs, "claude-opus-4-8") != normalize_messages(msgs, "claude-haiku-4-5")


def test_messages_block_content_flattened():
    # Anthropic block content flattens to the same form as the equivalent plain
    # string. Case/whitespace are preserved for LLM content (see normalize_messages),
    # so the two sides must match exactly, not just case-insensitively.
    a = normalize_messages([{"role": "user", "content": [{"type": "text", "text": "Hi There"}]}])
    b = normalize_messages([{"role": "user", "content": "Hi There"}])
    assert a == b


def test_messages_content_case_preserved():
    # Issue #12: LLM prompts differing only in case must NOT collapse to the same
    # cache identity (that would return a different intended answer).
    a = normalize_messages([{"role": "user", "content": "Hi There"}])
    b = normalize_messages([{"role": "user", "content": "hi there"}])
    assert a != b


def test_scope_is_run_scoped_not_agent_scoped():
    # Cross-agent reuse: scope must not depend on agent id.
    assert scope_key("run1", "pure") == "run:run1"


def test_state_bound_scope_folds_fingerprint():
    s1 = scope_key("run1", "state_bound", "user-a")
    s2 = scope_key("run1", "state_bound", "user-b")
    assert s1 != s2


def test_hash_deterministic_and_scoped():
    n = normalize_tool_args("search_docs", {"query": "x"})
    h1 = compute_hash(scope_key("run1", "pure"), n)
    h2 = compute_hash(scope_key("run1", "pure"), n)
    h3 = compute_hash(scope_key("run2", "pure"), n)
    assert h1 == h2
    assert h1 != h3  # different run scope -> different hash
    assert len(h1) == 64
