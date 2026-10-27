"""US CKD (N18) below age 60 and age-dependent CKD stage (USRDS 2018 ADR Vol 1, NHANES 2013-2016)."""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.patterns.markov import MarkovSpec, initial
from clinosim.modules.population.engine import generate_population

pytestmark = pytest.mark.unit


def test_markov_initial_uses_age_band_distribution() -> None:
    spec = MarkovSpec(
        state_name="s",
        icd_base="X",
        states=["A", "B"],
        initial_distribution={"A": 0.0, "B": 1.0},
        initial_distribution_by_age=[{"age_lo": 18, "age_hi": 39, "distribution": {"A": 1.0, "B": 0.0}}],
    )
    rng = np.random.default_rng(0)
    assert initial(rng, spec, age=30) == "A"
    assert initial(rng, spec, age=70) == "B"
    assert initial(rng, spec) == "B"


@pytest.fixture(scope="module")
def us_persons():
    return list(generate_population(10000, "US", np.random.default_rng(342)).persons.values())


def _has_n18(p) -> bool:
    return any(str(getattr(c, "code", c)).startswith("N18") for c in p.chronic_conditions)


@pytest.mark.parametrize(("lo", "hi", "low", "high"), [(18, 39, 0.045, 0.08), (40, 59, 0.08, 0.13)])
def test_ckd_prevalence_below_60_matches_usrds(us_persons, lo, hi, low, high) -> None:
    group = [p for p in us_persons if lo <= p.age <= hi]
    assert low <= sum(_has_n18(p) for p in group) / len(group) <= high


@pytest.mark.parametrize(("lo", "hi", "low", "high"), [(18, 39, 0.0, 0.15), (40, 59, 0.15, 0.40)])
def test_ckd_stage3_plus_share_by_age(us_persons, lo, hi, low, high) -> None:
    stages = [
        p.longitudinal_history[-1].chronic_stages.get("N18")
        for p in us_persons
        if lo <= p.age <= hi and _has_n18(p) and p.longitudinal_history
    ]
    stages = [s for s in stages if s]
    assert stages
    g3_plus = sum(s not in ("CKD G1", "CKD G2") for s in stages) / len(stages)
    assert low <= g3_plus <= high


def test_assignment_does_not_shift_master_rng(monkeypatch) -> None:
    """Only residents who receive N18 can differ (their per-person longitudinal
    sub-stream draws the CKD stage); everyone else is identical."""
    import clinosim.modules.population._ckd_under60 as mod

    with_ckd = generate_population(2000, "US", np.random.default_rng(7)).persons
    monkeypatch.setattr(mod, "load_ckd_under60_prevalence", lambda country: [])
    without = generate_population(2000, "US", np.random.default_rng(7)).persons
    assert with_ckd.keys() == without.keys()

    def codes(p) -> list[str]:
        return [str(getattr(c, "code", c)) for c in p.chronic_conditions]

    changed = 0
    for pid, p in with_ckd.items():
        q = without[pid]
        assert (p.age, p.sex, p.bmi) == (q.age, q.sex, q.bmi)
        if "N18" in codes(p) and "N18" not in codes(q):
            changed += 1
            continue
        assert codes(p) == codes(q)
    assert changed > 0
