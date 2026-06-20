"""Run the scripted waste task once and print the RunReport.

Usage:
    python scripts/run_waste_demo.py [redundant|baseline]

Uses Redis Cloud if REDIS_URL is reachable, otherwise the in-memory store so the
demo always runs. Prints a side-by-side baseline vs redundant summary.
"""

from __future__ import annotations

import sys

from redundant.config import SETTINGS
from redundant.demo import run_demo_task
from redundant.report import build_report


def _store():
    try:
        from redundant.redis_store import RedisStore

        s = RedisStore(SETTINGS)
        s.ping()
        print(f"[store] Redis Cloud @ {SETTINGS.redis_url.split('@')[-1]}")
        return s
    except Exception as exc:
        from redundant.memory_store import InMemoryStore

        print(f"[store] in-memory (Redis unavailable: {exc})")
        return InMemoryStore(SETTINGS)


def _run(mode: str, store):
    run_id = f"demo-{mode}"
    run_demo_task(run_id, mode, store)
    return build_report(run_id, store.read_events(run_id))


def main():
    store = _store()
    base = _run("baseline", store)
    red = _run("redundant", store)

    print("\n=== Redundant — Multi-Agent Cost Firewall ===\n")
    print(f"{'metric':<26}{'baseline':>14}{'redundant':>14}")
    print("-" * 54)
    rows = [
        ("attempted calls", base.attempted_calls, red.attempted_calls),
        ("executed calls", base.executed_calls, red.executed_calls),
        ("reused/blocked", base.reused_or_blocked_calls, red.reused_or_blocked_calls),
        ("redundant rate", f"{base.redundant_rate:.0%}", f"{red.redundant_rate:.0%}"),
        ("cost (USD)", f"${base.actual_cost_usd:.4f}", f"${red.actual_cost_usd:.4f}"),
        ("saved (USD)", f"${base.saved_cost_usd:.4f}", f"${red.saved_cost_usd:.4f}"),
        ("saved latency (ms)", base.saved_latency_ms, red.saved_latency_ms),
        ("saved tokens", base.saved_tokens, red.saved_tokens),
    ]
    for label, b, r in rows:
        print(f"{label:<26}{str(b):>14}{str(r):>14}")

    if red.worst_duplicate_cluster:
        print(f"\nworst duplicate cluster: {red.worst_duplicate_cluster}")
    print(f"\ntop fix: {red.fixes[0].title} — {red.fixes[0].code_hint}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] not in ("redundant", "baseline"):
        print(__doc__)
        sys.exit(1)
    main()
