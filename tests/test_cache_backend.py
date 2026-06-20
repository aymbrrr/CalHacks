import unittest

from redundant_app.cache import CachedCall, LocalLangCacheBackend, cache_prompt, input_hash_for, parse_cache_prompt


def cached_call(call_id: str, prompt: str, output: str = "cached output") -> CachedCall:
    return CachedCall(
        call_id=call_id,
        run_id="run-cache-test",
        agent_id="agent-a",
        call_kind="llm",
        tool_name="llm",
        prompt_or_args={"visible_task_summary": prompt},
        normalized_input=cache_prompt("llm", "llm", {"visible_task_summary": prompt}),
        input_hash=input_hash_for(cache_prompt("llm", "llm", {"visible_task_summary": prompt})),
        output=output,
        output_summary=output,
        cacheability="pure",
        input_tokens=20,
        output_tokens=12,
        cost_usd=0.001,
        latency_ms=120,
        created_at="2026-06-20T21:00:00Z",
    )


class CacheBackendTests(unittest.TestCase):
    def test_local_langcache_backend_finds_exact_hit(self):
        backend = LocalLangCacheBackend()
        entry = cached_call("call-001", "Summarize Redis LangCache for agent reuse.")
        backend.store(entry)

        lookup = backend.search(
            prompt=entry.normalized_input,
            attributes={"call_kind": "llm", "tool_name": "llm"},
            input_hash=entry.input_hash,
            similarity_threshold=0.45,
        )

        self.assertEqual(lookup.exact_entry.call_id, "call-001")
        self.assertEqual(lookup.similarity, 1.0)
        self.assertEqual(lookup.backend, "local-langcache-contract")

    def test_local_langcache_backend_finds_semantic_hit(self):
        backend = LocalLangCacheBackend()
        backend.store(cached_call("call-001", "Plan a Redis LangCache semantic cache for agents."))
        prompt = cache_prompt("llm", "llm", {"visible_task_summary": "Plan Redis LangCache caching for multi-agent apps."})

        lookup = backend.search(
            prompt=prompt,
            attributes={"call_kind": "llm", "tool_name": "llm"},
            input_hash=input_hash_for(prompt),
            similarity_threshold=0.45,
        )

        self.assertEqual(lookup.semantic_entry.call_id, "call-001")
        self.assertGreaterEqual(lookup.similarity, 0.45)

    def test_parse_cache_prompt_recovers_payload_for_langcache_hits(self):
        prompt = cache_prompt("tool", "search_docs", {"query": "Redis LangCache examples"})

        parsed = parse_cache_prompt(prompt)

        self.assertEqual(parsed["call_kind"], "tool")
        self.assertEqual(parsed["tool_name"], "search_docs")
        self.assertEqual(parsed["payload"]["query"], "Redis LangCache examples")


if __name__ == "__main__":
    unittest.main()
