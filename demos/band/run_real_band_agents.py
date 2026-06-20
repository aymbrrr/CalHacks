#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from demos.band.real_band_adapter import LocalRedundantBandAdapter, RealBandDemoState


AGENT_STARTUP_LINE = "REAL BAND MODE: starting ResearchAgent, ReportAgent, AuditAgent, VerifierAgent"


@dataclass(frozen=True)
class AgentSpec:
    display_name: str
    config_name: str
    config_aliases: tuple[str, ...]


AGENTS = (
    AgentSpec("ResearchAgent", "research_agent", ("researchagent",)),
    AgentSpec("ReportAgent", "report_agent", ("reportagent",)),
    AgentSpec("AuditAgent", "audit_agent", ("auditagent",)),
    AgentSpec("VerifierAgent", "verifier_agent", ("verifieragent",)),
)


def default_trace_path() -> Path:
    return Path(__file__).resolve().parent / "traces" / "band_demo_real_band_trace.json"


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def load_config_with_aliases(
    load_agent_config: Callable[[str], tuple[str, str]],
    spec: AgentSpec,
) -> tuple[str, str, str]:
    names = (spec.config_name, *spec.config_aliases)
    errors: list[str] = []
    for name in names:
        try:
            agent_id, api_key = load_agent_config(name)
            return agent_id, api_key, name
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError(
        f"Could not load Band credentials for {spec.display_name}. "
        f"Expected agent_config.yaml key '{spec.config_name}'. Tried: {', '.join(names)}. "
        f"Errors: {' | '.join(errors)}"
    )


async def run_agents(*, run_id: str, trace_out: Path) -> None:
    try:
        from band import Agent
        from band.config import load_agent_config
    except ImportError as exc:
        raise SystemExit(
            "Band SDK is not installed. Install it with `uv add band-sdk`, then run "
            "`uv run python demos/band/run_real_band_agents.py`."
        ) from exc

    load_dotenv_if_available()

    print(AGENT_STARTUP_LINE)
    print("Create a Band chat room, add the four remote agents, then send:")
    print("@ResearchAgent Research agent cost optimization tools, compare Redis/Sentry-style approaches, and produce a short recommendation.")

    state = RealBandDemoState(run_id=run_id, trace_out=trace_out)
    agent_runs = []
    for spec in AGENTS:
        agent_id, api_key, config_key = load_config_with_aliases(load_agent_config, spec)
        adapter = LocalRedundantBandAdapter(agent_name=spec.display_name, state=state)
        create_kwargs = {}
        if os.getenv("BAND_WS_URL"):
            create_kwargs["ws_url"] = os.environ["BAND_WS_URL"]
        if os.getenv("BAND_REST_URL"):
            create_kwargs["rest_url"] = os.environ["BAND_REST_URL"]
        agent = Agent.create(
            adapter=adapter,
            agent_id=agent_id,
            api_key=api_key,
            **create_kwargs,
        )
        print(f"REAL BAND MODE: loaded {spec.display_name} from agent_config.yaml key '{config_key}'")
        agent_runs.append(agent.run())

    await asyncio.gather(*agent_runs)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the real Band SDK remote agents for the Redundant demo.")
    parser.add_argument("--run-id", default="run-001-real-band")
    parser.add_argument("--trace-out", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trace_out = args.trace_out or default_trace_path()
    asyncio.run(run_agents(run_id=args.run_id, trace_out=trace_out))


if __name__ == "__main__":
    main()

