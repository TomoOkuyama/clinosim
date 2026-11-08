"""ED protocols are drawn only within their age range (Issue #2874)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from clinosim.modules.encounter.protocol import load_all_encounter_conditions, protocol_min_age
from clinosim.simulator.phases._ed_slot import _ed_condition_weight

pytestmark = pytest.mark.unit


def _weight(name: str, age: int) -> float:
    spec = load_all_encounter_conditions()[name]
    person = SimpleNamespace(age=age, date_of_birth=date(2025 - age, 1, 1), chronic_conditions=[], occupation="other")
    return _ed_condition_weight(name, spec, person, 3, {}, {}, visit_year=2025)


def test_adult_protocol_is_not_drawn_for_a_toddler() -> None:
    assert protocol_min_age(load_all_encounter_conditions()["uti_uncomplicated"]) == 18
    assert _weight("uti_uncomplicated", 1) == 0.0
    assert _weight("uti_uncomplicated", 30) > 0.0


def test_all_ages_protocol_has_no_floor() -> None:
    assert protocol_min_age(load_all_encounter_conditions()["concussion"]) is None
