"""Verifier seam (Chunk 3 / Terac replaces the default).

A Verifier decides whether a semantic candidate is *safe* to reuse, not merely
similar. The default is a cosine-threshold + cacheability rule. Chunk 3 swaps in
a Terac-trained verifier implementing the same interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from redundant.config import SETTINGS, Settings


@dataclass
class Candidate:
    """A prior call retrieved by vector search as a possible reuse source."""

    call_id: str
    cacheability: str
    similarity: float  # cosine similarity in [0, 1]
    output: str | None = None
    normalized_input: str = ""


@dataclass
class VerifierResult:
    approved: bool
    score: float
    reason: str


class Verifier(Protocol):
    def score(self, new_cacheability: str, candidate: Candidate) -> VerifierResult: ...


class ThresholdVerifier:
    """Default verifier: approve reuse when similarity clears the threshold and
    the call class is safe to reuse semantically.

    - pure: approve at/above threshold.
    - freshness_sensitive: require a higher bar (stale risk).
    - state_bound: never approve via pure semantics (needs matching state).
    - side_effecting: never approve.
    """

    def __init__(self, settings: Settings = SETTINGS):
        self.settings = settings

    def score(self, new_cacheability: str, candidate: Candidate) -> VerifierResult:
        sim = candidate.similarity
        if new_cacheability == "side_effecting":
            return VerifierResult(False, sim, "side-effecting: never reuse")
        if new_cacheability == "state_bound":
            return VerifierResult(False, sim, "state-bound: requires matching state fingerprint")
        if new_cacheability == "freshness_sensitive":
            ok = sim >= min(0.95, self.settings.sim_threshold + 0.07)
            return VerifierResult(ok, sim, "freshness-sensitive: high-bar match" if ok
                                  else "freshness-sensitive: below stale-safe bar")
        # pure
        ok = sim >= self.settings.sim_threshold
        return VerifierResult(ok, sim, "pure: similarity above threshold" if ok
                              else "pure: below similarity threshold")
