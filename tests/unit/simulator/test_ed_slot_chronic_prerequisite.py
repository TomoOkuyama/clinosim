"""ED exacerbation conditions are only drawn for residents with the underlying chronic disease."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.simulator.phases._ed_slot import _chronic_prefix_share, _ed_condition_weight

pytestmark = pytest.mark.unit

_ASTHMA = {"probability": 0.05, "requires_chronic_prefix": ["J45"]}
_SPRAIN = {"probability": 0.10}


def _person(*codes: str, age: int = 40, alive: bool = True):
    return SimpleNamespace(chronic_conditions=list(codes), age=age, occupation="office", is_alive=alive)


def test_resident_without_prerequisite_gets_zero_weight() -> None:
    assert _ed_condition_weight("asthma_attack_mild", _ASTHMA, _person("I10"), 1, {}, {"J45": 0.1}) == 0.0


def test_resident_with_prerequisite_gets_share_corrected_weight() -> None:
    w = _ed_condition_weight("asthma_attack_mild", _ASTHMA, _person("J45.20"), 1, {}, {"J45": 0.1})
    assert w == pytest.approx(0.05 / 0.1)


def test_condition_without_prerequisite_is_unchanged() -> None:
    assert _ed_condition_weight("ankle_sprain", _SPRAIN, _person(), 1, {}, {}) == pytest.approx(0.10)


def test_chronic_prefix_share_counts_living_residents() -> None:
    population = SimpleNamespace(
        persons={
            "a": _person("J45.20"),
            "b": _person("I10"),
            "c": _person("J45.909", alive=False),
            "d": _person(),
        }
    )
    assert _chronic_prefix_share(population, ["J45"]) == {"J45": pytest.approx(1 / 3)}


def test_ed_visit_count_uses_person_years_when_configured() -> None:
    from clinosim.simulator.phases._ed_slot import _ed_visit_count

    assert _ed_visit_count({"rate_per_1000_person_years": 380}, n_inpatient=999, n_persons=1000, total_months=24) == 760


def test_ed_visit_count_falls_back_to_rate_per_admitted() -> None:
    from clinosim.simulator.phases._ed_slot import _ed_visit_count

    assert _ed_visit_count({"rate_per_admitted": 2.5}, n_inpatient=100, n_persons=1000, total_months=24) == 250
