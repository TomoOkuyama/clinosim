"""Phase 4b.2.β Final-review I1 — engine-level drives for the Review Focus
input classes that structural tests only verified at the yaml surface.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.longitudinal.engine import (
    _attribute_in_scope,
    advance_one_year,
    initial_snapshot,
)
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.patterns.event import step
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _adult(sex: str = "M", age: int = 50, chronics: list[str] | None = None) -> PersonRecord:
    return PersonRecord(
        person_id=f"P-A-{sex}-{age}",
        household_id="H",
        sex=sex,
        age=age,
        date_of_birth=date(2024 - age, 1, 1),
        chronic_conditions=list(chronics or []),
    )


# ===========================================================================
# Review Focus #1 — pediatric person must not acquire adult chronic via event
# ===========================================================================


def test_pediatric_person_cannot_acquire_i10_via_engine_dispatch():
    """A 10-year-old is out of `[18, 120]` age band; `_attribute_in_scope`
    excludes them from the engine's event dispatch set. 2000 trials: zero
    I10 onsets."""
    specs = load_attribute_specs()
    i10 = specs["i10_onset"]
    child = PersonRecord(
        person_id="P-CHILD",
        household_id="H",
        sex="M",
        age=10,
        date_of_birth=date(2014, 1, 1),
        chronic_conditions=[],
    )
    # Engine-level scope gate rejects before dispatch.
    assert _attribute_in_scope(i10, child, 2024) is False
    # Step-level verification: even if the engine somehow dispatched,
    # `_resolve_base_rate` picks no matching band for age 10 → rate 0.
    fires = 0
    for seed in range(2000):
        rng = np.random.default_rng(seed)
        result = step(
            [],
            [],
            rng,
            i10.body,
            context={"continuous": {}, "age": 10, "chronic_conditions": []},
        )
        if result.fired:
            fires += 1
    assert fires == 0, f"pediatric I10 onset leaked: {fires}/2000"


# ===========================================================================
# Review Focus #5 — F32 compound multiplier scales base × DM × cancer
# ===========================================================================


def test_f32_onset_fires_more_often_for_diabetic_cancer_adult_than_clean_adult():
    """F32 base rate × DM-prefix multiplier × cancer-prefix multiplier.
    After the Phase 4b.2.β R3 revisit, DM and HF rules use
    `has_chronic_prefix` so `E11.9` + `C18` person compounds all 3
    rules (DM 2.0 × cancer 2.5 = 5.0× base vs clean person).

    Fire a Monte-Carlo over 400 draws of the 40-59 age band
    (base rate 0 in the yaml for 40-59 band — ends up at the terminal
    rate step; use the 18-39 band which has `rate=0.001540`). Compound
    expected rate ~0.0077. Clean adult rate ~0.0015. Observe ≥3× ratio
    at 400 trials (should see ~3 vs ~1 fires)."""
    specs = load_attribute_specs()
    body = specs["f32_onset"].body
    base_rate = body.base_rate_by_age_band[0].rate  # 18-39 band
    assert base_rate > 0

    def _run(chronic: list[str]) -> int:
        fires = 0
        for seed in range(2000):
            rng = np.random.default_rng(seed)
            result = step(
                chronic,
                [],
                rng,
                body,
                context={"continuous": {}, "age": 25, "chronic_conditions": chronic},
            )
            if result.fired:
                fires += 1
        return fires

    clean_fires = _run([])
    diabetic_cancer_fires = _run(["E11.9", "C18"])
    # DM ×2.0 × cancer ×2.5 = 5× → expected ~5× fire count.
    assert diabetic_cancer_fires >= 3 * clean_fires, (
        f"compound multiplier underwhelming: clean={clean_fires}, diabetic+cancer={diabetic_cancer_fires}"
    )


# ===========================================================================
# Review Focus #2 — legacy Z34/Z37 do not become fresh chronic conditions
# ===========================================================================


def test_engine_does_not_promote_legacy_state_period_codes():
    """A person carrying Z34 / Z37 as a legacy pre-migration CIF marker
    must NOT see those codes appear in `new_complications` or be
    re-appended to `chronic_conditions`. The migration deliberately
    omits z34_onset / z37_onset yamls so the engine has no attribute
    that emits those codes.
    """
    person = PersonRecord(
        person_id="P-LEGACY",
        household_id="H",
        sex="F",
        age=44,
        date_of_birth=date(1980, 1, 1),
        chronic_conditions=["Z34", "Z37", "I10"],
    )
    initial_snapshot(person, year=2024, init_rng=np.random.default_rng(0))
    advance_one_year(person, year=2025, year_rng=np.random.default_rng(0))

    # Z34 / Z37 stay as inert passthrough on chronic_conditions (no new
    # append, no duplicate).
    assert person.chronic_conditions.count("Z34") == 1
    assert person.chronic_conditions.count("Z37") == 1

    # No event emitted Z34 / Z37 as a new complication in any year snap.
    for snap in person.longitudinal_history:
        assert "Z34" not in snap.new_complications
        assert "Z37" not in snap.new_complications


# ===========================================================================
# Final-review I4 — Monte-Carlo marginal preservation (replaces the deleted
# test_chronic_onset_approximate_marginal_over_decade coverage)
# ===========================================================================


def test_i10_marginal_approaches_target_prevalence_over_decade():
    """A cohort of 1000 initially-chronic-free adults age 20 → 30 across
    10 sim years. End-of-decade I10 prevalence should accumulate roughly
    `1 - (1 - 0.013785) ** 10 ≈ 0.13`. Headroom ±50 % for stochasticity
    at p=1000 and the age-band crossover at 40 (none here — the cohort
    starts age 20, stays in the 18-39 band throughout)."""
    specs = load_attribute_specs()
    i10 = specs["i10_onset"]
    rng = np.random.default_rng(42)
    cohort_size = 1000
    acquired = 0
    for i in range(cohort_size):
        age = 20
        has_i10 = False
        for _year in range(10):
            if has_i10:
                break
            # Step is deterministic given context + rng state; use the
            # cohort rng for per-person per-year draws.
            result = step(
                [],
                [],
                rng,
                i10.body,
                context={"continuous": {}, "age": age, "chronic_conditions": []},
            )
            if result.fired:
                has_i10 = True
            age += 1
        if has_i10:
            acquired += 1

    prev = acquired / cohort_size
    expected = 1 - (1 - 0.013785) ** 10  # ~0.1296
    assert 0.07 <= prev <= 0.20, (
        f"I10 10y marginal prevalence out of band: {prev:.4f} (expected ~{expected:.4f} ± 50 %)"
    )
