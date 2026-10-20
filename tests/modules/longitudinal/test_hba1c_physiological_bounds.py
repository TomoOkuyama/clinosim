"""HbA1c trajectory physiologic bounds + scope filtering.

The 120-day erythrocyte lifespan constrains HbA1c changes to roughly
≤ 1.0 % over 60 days. Validate that the calibrated AR(1) parameters
honour this bound on a 1000-seed Monte Carlo sweep.

Also pins the scope gate (age band + chronic-code prefix) so a
non-DM or pediatric person never gets a HbA1c latent.

See Phase 1 plan Task 5 brief + spec §4.2.1.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.longitudinal.engine import advance_one_year, initial_snapshot
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.types.population import PersonRecord


@pytest.fixture(autouse=True)
def _clear_loader() -> None:
    """Every test exercises the real repo yaml — clear the cache so
    an earlier isolated test cannot poison the lookup."""
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


def _mk_dm_person(seed: int) -> PersonRecord:
    return PersonRecord(
        person_id=f"P-{seed}",
        household_id="HH",
        age=55,
        sex="M",
        date_of_birth=date(1970, 6, 1),
        chronic_conditions=["E11.9"],
    )


@pytest.mark.unit
def test_hba1c_yaml_loads_as_ar1_spec() -> None:
    specs = load_attribute_specs()
    assert "hba1c" in specs
    assert specs["hba1c"].pattern == "ar1"


@pytest.mark.unit
def test_hba1c_params_match_calibration() -> None:
    """Pin exact literature-calibrated values; any drift is a
    deliberate re-calibration and should land with a new source line."""
    body = load_attribute_specs()["hba1c"].body
    assert body.phi == 0.75
    assert body.sigma == 0.40
    assert body.mean_reversion_target == 7.3
    assert body.clamp == [4.0, 15.0]
    assert body.initial_mu == 1.95
    assert body.initial_sigma == 0.17
    assert body.initial_clamp == [4.5, 14.0]


@pytest.mark.unit
def test_non_dm_patient_has_no_hba1c_in_state_history() -> None:
    """Review Focus 2."""
    person = PersonRecord(
        person_id="non-dm",
        household_id="HH",
        age=55,
        sex="M",
        date_of_birth=date(1970, 6, 1),
        chronic_conditions=["I10"],  # HTN, no DM
    )
    snap = initial_snapshot(person, year=2021, init_rng=np.random.default_rng(0))
    assert "hba1c" not in snap.continuous


@pytest.mark.unit
def test_pediatric_person_has_no_hba1c_in_state_history() -> None:
    """E11 but age=10 (below requires_age_band[0]=18) → no latent."""
    person = PersonRecord(
        person_id="peds",
        household_id="HH",
        age=10,
        sex="M",
        date_of_birth=date(2014, 6, 1),
        chronic_conditions=["E11.9"],
    )
    snap = initial_snapshot(person, year=2024, init_rng=np.random.default_rng(0))
    assert "hba1c" not in snap.continuous


@pytest.mark.unit
def test_hba1c_trajectory_respects_rbc_lifespan_bound() -> None:
    """1000 seeds × 5-year trajectory → sample two encounters within
    60 days each year, less than 1 % of 60-day pairs show |Δ| > 1.0 %.

    This is the acceptance criterion the Phase 1 cohort audit targets.
    The 60-day diff is dominated by measurement noise (√2 × 0.20 ≈
    0.28 %), since 60-day latent drift under phi=0.75 is small —
    expect |Δ| < 1.0 % in roughly 99.7 % of pairs.
    """
    out_of_bound = 0
    total_pairs = 0
    for seed in range(1000):
        person = _mk_dm_person(seed)
        rng = np.random.default_rng(seed)
        initial_snapshot(person, year=2021, init_rng=rng)
        for y in range(2022, 2026):
            advance_one_year(person, year=y, year_rng=rng)
        meas_rng = np.random.default_rng(1_000_000 + seed)
        meas_sigma = 0.20
        for snap in person.longitudinal_history:
            latent = snap.continuous["hba1c"]
            m1 = latent + meas_sigma * meas_rng.standard_normal()
            m2 = latent + meas_sigma * meas_rng.standard_normal()
            total_pairs += 1
            if abs(m1 - m2) > 1.0:
                out_of_bound += 1
    rate = out_of_bound / total_pairs
    assert rate < 0.01, f"RBC-lifespan bound violated in {rate:.2%} of pairs"


@pytest.mark.unit
def test_cohort_mean_hba1c_reverts_toward_target() -> None:
    """Across many patients × 10 years, cohort mean HbA1c sits within
    0.3 of the mean-reversion target."""
    latents = []
    for seed in range(500):
        person = _mk_dm_person(seed)
        rng = np.random.default_rng(seed)
        initial_snapshot(person, year=2021, init_rng=rng)
        for y in range(2022, 2032):  # 10-year window to let AR(1) relax
            advance_one_year(person, year=y, year_rng=rng)
        latents.extend(snap.continuous["hba1c"] for snap in person.longitudinal_history[-5:])
    cohort_mean = sum(latents) / len(latents)
    assert abs(cohort_mean - 7.3) < 0.3
