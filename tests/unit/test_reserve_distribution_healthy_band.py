"""Reserve distribution + baseline calibration invariants (Issue #416).

These tests exist to lock the fix for the systematic drift documented in
Issue #416: three physiological reserves (renal / cardiac / hepatic)
shared the same ``beta(8, 2)`` distribution regardless of chronic-
condition status or age, and two derive_lab_values baselines (Albumin
base 4.2, base_cr F 0.7) sat outside the JP reference-range center.
That combination pushed the healthy-young cohort out of the JP reference
band on K / Cre(M) / Cre(F) / Alb and let Troponin_I read positive on
healthy patients.

Test A: healthy-young in-band assertion (95% threshold).
Test B: RNG cursor preservation micro-check (companion to the real-cohort
        byte-diff in the PR body; the wall-clock check for
        "beta parameter change is cursor-neutral" belongs here so the
        invariant survives future refactors).
Test C: physiology derivation invariants — pin the reserve-1.0 baseline
        so a silent drift in ``derive_lab_values`` math can't slip in
        while the distribution is being rebalanced.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.physiology.engine import derive_lab_values
from clinosim.types import PhysiologicalState

# ---------------------------------------------------------------------------
# Test A — healthy-young in-band on K / Cre(M/F) / Alb

# JP reference-range bands (JCCLS 共用基準範囲 2022) — the values the fix targets.
_JP_REF = {
    "K": (3.6, 4.8),
    "Cre_M": (0.65, 1.07),
    "Cre_F": (0.46, 0.79),
    "Albumin": (4.1, 5.1),
}

# Pipeline noise coefficients from modules/observation/engine.py
# (BIOLOGICAL_CV + ANALYTICAL_CV). Kept inline because the invariant
# this test guards is "the fix preserves the JP band under noise,"
# not the noise coefficients themselves.
_BIOLOGICAL_CV = {"K": 0.046, "Creatinine": 0.056, "Albumin": 0.032}
_ANALYTICAL_CV = {"K": 0.015, "Creatinine": 0.030, "Albumin": 0.025}


def _healthy_young_state() -> PhysiologicalState:
    """A completely healthy, fully perfused adult with no inflammation."""
    return PhysiologicalState(
        renal_function=1.0,
        cardiac_function=1.0,
        hepatic_function=1.0,
        perfusion_status=1.0,
        inflammation_level=0.0,
        anemia_level=0.0,
        coagulation_status=0.0,
        volume_status=0.0,
        sodium_status=0.0,
        glucose_status=0.0,
        ph_status=0.0,
    )


def _simulate_healthy_young(sex: str, n: int, seed: int) -> dict[str, np.ndarray]:
    """Simulate n healthy-young patients (age_penalty=0, no chronic, infl=0)
    by drawing reserves from the current activator distribution, mapping
    through derive_lab_values, and adding the observation-layer noise."""
    from clinosim.modules.patient import activator

    rng = np.random.default_rng(seed)
    # Match activator.py's clamp: max(0.1, beta - age_penalty). age_penalty=0
    # for age < 40, so we just call beta with the same shape the activator
    # uses and take max(0.1, ...) to preserve the floor semantics.
    reserves_r = np.clip(rng.beta(*activator._RESERVE_BETA_PARAMS, n), 0.1, 1.0)
    reserves_c = np.clip(rng.beta(*activator._RESERVE_BETA_PARAMS, n), 0.1, 1.0)
    reserves_h = np.clip(rng.beta(*activator._RESERVE_BETA_PARAMS, n), 0.1, 1.0)

    K = np.empty(n)
    Cre = np.empty(n)
    Alb = np.empty(n)
    for i in range(n):
        state = _healthy_young_state()
        state.renal_function = float(reserves_r[i])
        state.cardiac_function = float(reserves_c[i])
        state.hepatic_function = float(reserves_h[i])
        state.perfusion_status = min(1.0, state.cardiac_function * 0.8 + 0.2)
        labs = derive_lab_values(state, sex=sex, age=25, has_diabetes=False)
        # Pipeline noise: observed = true + N(0, true*CVi) + N(0, true*CVa)
        for analyte, dst, arr in (("K", "K", K), ("Creatinine", "Creatinine", Cre), ("Albumin", "Albumin", Alb)):
            t = labs[analyte]
            cvi = _BIOLOGICAL_CV[analyte]
            cva = _ANALYTICAL_CV[analyte]
            arr[i] = t + rng.normal(0, t * cvi) + rng.normal(0, t * cva)
    return {"K": K, "Cre": Cre, "Albumin": Alb}


def _in_band_ratio(values: np.ndarray, lo: float, hi: float) -> float:
    return float(np.mean((values >= lo) & (values <= hi)))


@pytest.mark.unit
def test_healthy_young_K_lands_in_jp_band() -> None:
    """≥95% of healthy young must fall inside JP ref K [3.6, 4.8]."""
    vals = _simulate_healthy_young(sex="M", n=10_000, seed=42)["K"]
    lo, hi = _JP_REF["K"]
    assert _in_band_ratio(vals, lo, hi) >= 0.95


@pytest.mark.unit
def test_healthy_young_Cre_M_lands_in_jp_band() -> None:
    """≥95% of healthy young males must fall inside JP ref Cre(M) [0.65, 1.07]."""
    vals = _simulate_healthy_young(sex="M", n=10_000, seed=42)["Cre"]
    lo, hi = _JP_REF["Cre_M"]
    assert _in_band_ratio(vals, lo, hi) >= 0.95


@pytest.mark.unit
def test_healthy_young_Cre_F_lands_in_jp_band() -> None:
    """≥95% of healthy young females must fall inside JP ref Cre(F) [0.46, 0.79].

    The 95% target requires ``base_cr`` for females to sit near the JP-ref
    center (0.625), not the current 0.7 (upper-tail-hugging).
    """
    vals = _simulate_healthy_young(sex="F", n=10_000, seed=42)["Cre"]
    lo, hi = _JP_REF["Cre_F"]
    assert _in_band_ratio(vals, lo, hi) >= 0.95


@pytest.mark.unit
def test_healthy_young_Albumin_lands_in_jp_band() -> None:
    """≥95% of healthy young must fall inside JP ref Alb [4.1, 5.1].

    Requires the Alb baseline to move from 4.2 (current, hugging the JP
    lower bound) to a center-oriented value (~4.6).
    """
    vals = _simulate_healthy_young(sex="M", n=10_000, seed=42)["Albumin"]
    lo, hi = _JP_REF["Albumin"]
    assert _in_band_ratio(vals, lo, hi) >= 0.95


# ---------------------------------------------------------------------------
# Test B — RNG cursor preservation micro-check


@pytest.mark.unit
def test_reserve_beta_parameters_preserve_rng_cursor() -> None:
    """The reserve beta parameters ``(a, 2)`` class preserves the master
    RNG cursor (numpy's Cheng BB algorithm consumes the same number of
    uniforms per beta call for any ``a > 1, b = 2``). This is what lets
    the fix change reserve values without shifting downstream draws
    (names / addresses / chronic-condition IDs / disease selection / lab
    noise). Companion real-cohort byte-diff is documented in the PR body.
    """
    from clinosim.modules.patient import activator

    seed = 300
    n = 300

    def _next_after(a: float, b: float) -> float:
        r = np.random.default_rng(seed)
        r.beta(a, b, n)
        return float(r.random())

    baseline = _next_after(8, 2)  # legacy shape
    current = _next_after(*activator._RESERVE_BETA_PARAMS)
    assert current == baseline, (
        f"reserve beta({activator._RESERVE_BETA_PARAMS}) is not RNG-cursor-neutral "
        f"vs beta(8, 2): {current!r} != {baseline!r}"
    )


# ---------------------------------------------------------------------------
# Test C — physiology derivation invariants (reserve = 1.0 baselines)


@pytest.mark.unit
def test_derive_lab_values_reserve1_is_pinned() -> None:
    """Pin ``derive_lab_values`` output at reserve = 1.0 so a silent drift
    in the math can't slip in during the fix.

    Values are the calibrated bases, NOT textbook healthy values:
      K       = 4.0        (no calibration — healthy-young in-band 99.07%)
      Cre(M)  = 0.80625    (= 0.86 × 0.9375, JCCLS M ref center × E[reserve])
      Cre(F)  = 0.5859375  (= 0.625 × 0.9375, JCCLS F ref center × E[reserve])
      Alb     = 4.69375    (= 4.6 + (1 - 0.9375) × 1.5, subtractive offset
                             so the cohort MEDIAN lands on JCCLS center 4.6)

    Reserve = 1.0 here is 'slightly better than typical' by design; the
    cohort median (not this pinned value) is what lands on the JCCLS center.
    """
    state = _healthy_young_state()

    labs_M = derive_lab_values(state, sex="M", age=25, has_diabetes=False)
    labs_F = derive_lab_values(state, sex="F", age=25, has_diabetes=False)

    assert labs_M["K"] == pytest.approx(4.0)
    assert labs_M["Creatinine"] == pytest.approx(0.80625)
    assert labs_F["Creatinine"] == pytest.approx(0.5859375)
    assert labs_M["Albumin"] == pytest.approx(4.69375)
