"""Scripted multi-agent waste task (stand-in for the Band workflow, Chunk 2).

Two agents research overlapping topics and write a report, deliberately repeating
work: duplicate searches, the same source summarized twice, a cross-agent repo
scan, a small loop, and a duplicated side-effect. With the firewall enabled, the
duplicates collapse into reuse/blocks; in baseline mode everything executes.
"""

from __future__ import annotations

from redundant.config import SETTINGS, Settings
from redundant.runtime import Redundant
from redundant import tools


SOURCE = "https://example.com/agent-cost-optimization"


def _fake_openai(settings: Settings):
    """Deterministic offline LLM so the demo runs without an OpenAI key."""

    class _Message:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Message(content)

    class _Resp:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    class _Completions:
        def create(self, model, messages, **kwargs):
            last = messages[-1]["content"] if messages else ""
            return _Resp(f"[report:{str(last)[:60]}]")

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    # Use the deterministic offline LLM when there's no key OR offline mode is
    # forced (hermetic tests / zero-cost demos). Only a real run with a key and
    # offline disabled talks to OpenAI.
    offline = settings.embeddings_offline or not settings.openai_api_key
    return _Client() if offline else None


def run_demo_task(run_id: str, mode: str, store, settings: Settings = SETTINGS) -> None:
    """Execute the scripted task, emitting events to `store`. mode in
    {baseline, redundant}. (replay is handled by the API, not here.)"""
    tools.SIDE_EFFECT_LOG.sends.clear()
    enabled = mode != "baseline"
    r = Redundant(
        run_id=run_id, store=store, settings=settings,
        openai_client=_fake_openai(settings), enabled=enabled,
    )

    # 1. Research agent gathers sources.
    r.tool("research-agent", "search_docs", {"query": "agent cost optimization tools"})
    r.tool("research-agent", "scan_repo", {"topic": "redis caching"})
    r.tool("research-agent", "summarize_page", {"url_or_text": SOURCE})
    r.tool("research-agent", "compare_tools", {"tool_a": "redis", "tool_b": "sentry"})

    # 2. Report agent repeats overlapping work (the waste).
    r.tool("report-agent", "search_docs", {"query": "agent cost optimization approaches"})  # paraphrase -> semantic
    r.tool("report-agent", "summarize_page", {"url_or_text": SOURCE})                        # exact dup
    r.tool("report-agent", "scan_repo", {"topic": "redis caching"})                          # cross-agent exact dup

    # 3. A small loop (same call hammered).
    for _ in range(3):
        r.tool("research-agent", "search_docs", {"query": "redundant agent spend"})

    # 4. A duplicated side-effect (must never replay).
    r.tool("report-agent", "send_email", {"to": "team@demo.com", "subject": "Findings"})
    r.tool("report-agent", "send_email", {"to": "team@demo.com", "subject": "Findings"})

    # 5. Final report write-up (LLM).
    r.llm("report-agent",
          [{"role": "user", "content": "Write a short recommendation from the research."}],
          model=settings.default_model)
