"""Markov discrete-stage pattern.

One of three trajectory patterns the longitudinal engine composes
(§3 of the Phase 1 spec, §4.2.2 of the Phase 2 spec). Each year the
step draws from the per-state transition row; terminal rows
(empty mapping) absorb. A pre-step multiplier (e.g. from
``_comorbidity_multiplier`` under Phase 2 Task 7) scales each
candidate probability, clamped to ``[0.0, 1.0]`` per candidate
before the uniform draw.

Spec: docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field


class AgeBandDistribution(BaseModel):
    """Sim-start stage distribution for persons aged ``age_lo``..``age_hi``."""

    age_lo: int
    age_hi: int
    distribution: dict[str, float] = Field(..., min_length=1)


class MarkovSpec(BaseModel):
    """Parameters for a discrete-stage Markov attribute."""

    state_name: str
    icd_base: str
    states: list[str] = Field(..., min_length=1)
    initial_distribution: dict[str, float] = Field(..., min_length=1)
    # Optional age-band overrides of ``initial_distribution`` (first match wins).
    initial_distribution_by_age: list[AgeBandDistribution] = Field(default_factory=list)
    transitions: dict[str, dict[str, float]] = Field(default_factory=dict)


def step(
    prev: str,
    rng: np.random.Generator,
    spec: MarkovSpec,
    *,
    multiplier: float = 1.0,
) -> str:
    """Advance the discrete stage one year under the Markov transition row.

    Terminal (empty row) returns ``prev`` unchanged. ``multiplier``
    scales each candidate probability and the result is clamped
    per-candidate to ``[0.0, 1.0]`` before the cumulative uniform
    draw. An unknown ``prev`` state raises ``ValueError``.
    """
    if prev not in spec.states:
        raise ValueError(f"unknown Markov state {prev!r} for icd_base={spec.icd_base}")
    row = spec.transitions.get(prev, {})
    if not row:
        return prev
    u = float(rng.random())
    cum = 0.0
    for next_state, prob in row.items():
        scaled = max(0.0, min(1.0, float(prob) * float(multiplier)))
        cum += scaled
        if u < cum:
            return next_state
    return prev


def initial(rng: np.random.Generator, spec: MarkovSpec, *, age: int | None = None) -> str:
    """Draw the sim-start stage from the categorical ``initial_distribution``.

    When ``age`` falls in an ``initial_distribution_by_age`` band, that band's
    distribution is used instead; either way exactly one uniform is drawn.

    States absent from ``initial_distribution`` carry implicit weight
    0. Weights are consumed in dict-insertion order; if the uniform
    draw falls past the cumulative sum, the last keyed state is
    returned (guards against float-sum rounding).
    """
    distribution = spec.initial_distribution
    if age is not None:
        for band in spec.initial_distribution_by_age:
            if band.age_lo <= age <= band.age_hi:
                distribution = band.distribution
                break
    u = float(rng.random())
    cum = 0.0
    last_state = next(iter(distribution))
    for state, weight in distribution.items():
        cum += float(weight)
        last_state = state
        if u < cum:
            return state
    return last_state
