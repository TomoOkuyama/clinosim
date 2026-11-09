"""No documented allergy below the age it can have been documented (Issue #3108)."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.allergy.engine import allergy_enricher, load_allergen_config

pytestmark = pytest.mark.unit

_START = date(2024, 1, 1)


def _persons(n: int, age_days: int) -> list[SimpleNamespace]:
    dob = _START - timedelta(days=age_days)
    return [
        SimpleNamespace(
            person_id=f"P-{i:05d}",
            age=age_days // 365,
            date_of_birth=dob,
            sex="F",
            chronic_conditions=[],
            allergies=None,
        )
        for i in range(n)
    ]


def _run(persons: list[SimpleNamespace]) -> list[SimpleNamespace]:
    ctx = SimpleNamespace(
        master_seed=42,
        population=SimpleNamespace(persons={p.person_id: p for p in persons}),
        records=[],
        config=SimpleNamespace(time_range=(_START, date(2024, 12, 31))),
    )
    allergy_enricher(ctx)
    return persons


def _categories(persons: list[SimpleNamespace]) -> set[str]:
    return {a.category for p in persons for a in p.allergies if not a.is_nka}


def _min_months() -> dict[str, int]:
    return load_allergen_config()["minimum_age_months"]


def test_a_newborn_has_no_documented_allergy() -> None:
    for p in _run(_persons(3000, 0)):
        assert len(p.allergies) == 1 and p.allergies[0].is_nka


def test_a_person_born_after_the_start_has_no_documented_allergy() -> None:
    for p in _run(_persons(1000, -40)):
        assert [a.is_nka for a in p.allergies] == [True]


@pytest.mark.parametrize("category", ["medication", "food", "environment"])
def test_no_allergy_of_a_category_below_its_minimum_age(category: str) -> None:
    months = _min_months()[category]
    below = _run(_persons(3000, months * 30 - 20))
    assert category not in _categories(below)
    at_age = _run(_persons(3000, months * 31 + 20))
    assert category in _categories(at_age)


def test_a_drug_allergy_is_not_sampled_below_the_minimum_age() -> None:
    # Old enough for a food allergy, too young for a documented drug allergy.
    persons = _run(_persons(3000, 300))
    assert _min_months()["food"] * 31 < 300 < _min_months()["medication"] * 30
    assert "medication" not in _categories(persons)
    assert "food" in _categories(persons)


def test_kept_allergies_are_numbered_from_one() -> None:
    for p in _run(_persons(3000, 300)):
        ids = [a.allergy_id for a in p.allergies if not a.is_nka]
        assert ids == [str(i + 1) for i in range(len(ids))]


def _summary(persons: list[SimpleNamespace]) -> list[tuple]:
    return [
        tuple((a.allergen_code, a.clinical_status, a.verification_status) for a in p.allergies if not a.is_nka)
        for p in persons
    ]


def test_the_gate_removes_outcomes_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import copy

    import clinosim.modules.allergy.engine as engine

    gated_children = _summary(_run(_persons(2000, 300)))
    gated_adults = _summary(_run(_persons(2000, 40 * 365)))
    ungated = copy.deepcopy(load_allergen_config())
    ungated["minimum_age_months"] = {c: 0 for c in ungated["minimum_age_months"]}
    monkeypatch.setattr(engine, "load_allergen_config", lambda: ungated)
    # Adults: identical. Children: a subset of the ungated draw, in order.
    assert _summary(_run(_persons(2000, 40 * 365))) == gated_adults
    for kept, full in zip(gated_children, _summary(_run(_persons(2000, 300))), strict=True):
        assert [x for x in full if x in kept] == list(kept)
