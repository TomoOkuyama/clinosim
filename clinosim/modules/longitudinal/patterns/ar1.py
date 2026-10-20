"""AR(1) continuous-latent pattern.

One of three trajectory patterns the longitudinal engine composes
(§3 of the Phase 1 spec). The AR(1) step advances a continuous
latent one year forward:

    h_{t+1} = phi * h_t + (1 - phi) * target + sigma * N(0, 1)

Clamped to a physiologic range. The initial draw seeds the chain
from a lognormal distribution matching the cohort-entry distribution
for incident DM; the Phase 1 attribute (HbA1c) uses literature-
calibrated values from DCCT/EDIC / ADVANCE / Wu 2023 meta-analysis.
"""

from __future__ import annotations

import math

import numpy as np
from pydantic import BaseModel, Field


class AR1Spec(BaseModel):
    """Parameters for an AR(1) continuous-latent attribute."""

    latent_name: str
    phi: float = Field(..., ge=0.0, le=1.0)
    sigma: float = Field(..., ge=0.0)
    mean_reversion_target: float
    clamp: list[float] = Field(..., min_length=2, max_length=2)
    initial_mu: float
    initial_sigma: float = Field(..., ge=0.0)
    initial_clamp: list[float] = Field(..., min_length=2, max_length=2)


def step(prev: float, rng: np.random.Generator, spec: AR1Spec) -> float:
    """Advance the latent one year under the AR(1) step formula."""
    raw = spec.phi * prev + (1.0 - spec.phi) * spec.mean_reversion_target + spec.sigma * float(rng.standard_normal())
    return float(np.clip(raw, spec.clamp[0], spec.clamp[1]))


def initial(rng: np.random.Generator, spec: AR1Spec) -> float:
    """Draw the sim-start latent from the initial lognormal."""
    draw = math.exp(spec.initial_mu + spec.initial_sigma * float(rng.standard_normal()))
    return float(np.clip(draw, spec.initial_clamp[0], spec.initial_clamp[1]))
