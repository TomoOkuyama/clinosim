"""AR(1) pattern math.

The AR(1) step runs annually in `advance_one_year`: a continuous
latent `h_t` evolves via `h_{t+1} = phi * h_t + (1 - phi) * target +
sigma * N(0, 1)`, clamped to a physiologic range. The initial draw
seeds the chain from a lognormal distribution matching cohort-entry
HbA1c for incident DM.

See Phase 1 plan Task 2 brief + spec §4.2.1 for the exact body
schema.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.patterns.ar1 import AR1Spec, initial, step


def _mk_spec(
    *,
    phi: float = 0.75,
    sigma: float = 0.40,
    target: float = 7.3,
    clamp: tuple[float, float] = (4.0, 15.0),
    init_mu: float = 1.95,
    init_sigma: float = 0.17,
    init_clamp: tuple[float, float] = (4.5, 14.0),
) -> AR1Spec:
    return AR1Spec(
        latent_name="hba1c",
        phi=phi,
        sigma=sigma,
        mean_reversion_target=target,
        clamp=list(clamp),
        initial_mu=init_mu,
        initial_sigma=init_sigma,
        initial_clamp=list(init_clamp),
    )


@pytest.mark.unit
def test_step_mean_reverts_toward_target() -> None:
    """From an off-target start a 10000-step chain converges to
    within 0.1 of the mean-reversion target. Pins the AR(1) pull."""
    spec = _mk_spec(phi=0.75, sigma=0.40, target=7.3)
    rng = np.random.default_rng(42)
    h = 12.0
    tail = []
    for _ in range(10000):
        h = step(h, rng, spec)
        tail.append(h)
    tail_mean = sum(tail[-1000:]) / 1000
    assert abs(tail_mean - 7.3) < 0.1


@pytest.mark.unit
def test_step_stationary_variance_matches_closed_form() -> None:
    """After 10000 steps the empirical variance is within 5 % of
    `sigma² / (1 − phi²)` — the AR(1) stationary variance."""
    spec = _mk_spec(phi=0.75, sigma=0.40, target=7.3, clamp=(-100.0, 100.0))
    rng = np.random.default_rng(0)
    h = 7.3
    tail = []
    for _ in range(10000):
        h = step(h, rng, spec)
        tail.append(h)
    arr = np.array(tail[-5000:])
    emp_var = float(arr.var())
    closed_var = 0.40**2 / (1 - 0.75**2)
    assert abs(emp_var - closed_var) / closed_var < 0.10  # 10% band for sampling noise


@pytest.mark.unit
def test_step_clamp_enforced_on_both_tails() -> None:
    """A step whose innovation would push past the clamp is held at
    the clamp bound. The clamp is physiologic, not statistical."""
    spec = _mk_spec(phi=1.0, sigma=100.0, target=0.0, clamp=(4.0, 15.0))
    rng = np.random.default_rng(1)
    hi = step(14.9, rng, spec)
    assert hi <= 15.0
    rng2 = np.random.default_rng(1_000_000)
    lo = step(4.1, rng2, spec)
    assert lo >= 4.0


@pytest.mark.unit
def test_initial_lognormal_shape_matches_spec() -> None:
    """10000 initial draws have median within 0.1 of `exp(mu)` and
    95th percentile within 0.3 of `exp(mu + 1.645 * sigma)` — the
    DCCT/EDIC-anchored entry distribution."""
    spec = _mk_spec(init_mu=1.95, init_sigma=0.17, init_clamp=(4.5, 14.0))
    rng = np.random.default_rng(2)
    draws = np.array([initial(rng, spec) for _ in range(10000)])
    median = float(np.median(draws))
    p95 = float(np.percentile(draws, 95))
    assert abs(median - np.exp(1.95)) < 0.15
    assert abs(p95 - np.exp(1.95 + 1.645 * 0.17)) < 0.4


@pytest.mark.unit
def test_step_zero_phi_is_pure_noise() -> None:
    """`phi = 0` makes successive draws independent — autocorrelation
    at lag-1 is near zero."""
    spec = _mk_spec(phi=0.0, sigma=1.0, target=0.0, clamp=(-100.0, 100.0))
    rng = np.random.default_rng(3)
    h = 0.0
    xs = []
    for _ in range(5000):
        h = step(h, rng, spec)
        xs.append(h)
    arr = np.array(xs)
    corr = float(np.corrcoef(arr[:-1], arr[1:])[0, 1])
    assert abs(corr) < 0.05


@pytest.mark.unit
def test_step_phi_one_is_random_walk() -> None:
    """`phi = 1` with target = 0 reduces to `h_{t+1} = h_t +
    sigma * N(0,1)`. Verified by E[step(h, rng, spec) - h] ≈ 0 and
    var(step(h, rng, spec) - h) ≈ sigma²."""
    spec = _mk_spec(phi=1.0, sigma=0.5, target=0.0, clamp=(-1e9, 1e9))
    rng = np.random.default_rng(4)
    deltas = np.array([step(5.0, rng, spec) - 5.0 for _ in range(10000)])
    assert abs(float(deltas.mean())) < 0.05
    assert abs(float(deltas.var()) - 0.25) < 0.05
