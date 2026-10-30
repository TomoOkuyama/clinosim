"""ED conditions are gated on the age at the visit (Issue #2174)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.simulator.phases._ed_slot import _ed_condition_weight

pytestmark = pytest.mark.unit

_ADULT_ONLY = {"min_age": 18, "probability": 0.1}

# Presentations not seen in infants and toddlers, with the youngest age the
# protocol may be drawn for.
_MIN_AGES = {
    "abdominal_pain_nonspecific": 2,
    "ankle_sprain": 5,
    "elderly_fall": 65,
    "epistaxis": 2,
    "eye_foreign_body": 3,
    "low_back_pain": 16,
    "migraine": 6,
    "renal_colic": 16,
    "rib_fracture": 12,
    "shoulder_dislocation": 12,
    "syncope": 6,
    "urinary_retention": 18,
    "vertigo": 12,
    "wrist_fracture": 4,
}


def _person(static_age: int, birth_year: int) -> SimpleNamespace:
    return SimpleNamespace(age=static_age, date_of_birth=date(birth_year, 6, 1), chronic_conditions=[], occupation="")


def test_weight_uses_age_in_the_visit_year() -> None:
    # Generated at 16 in 2024 (static age), 18 in the 2026 visit year.
    p = _person(16, 2008)
    assert _ed_condition_weight("x", _ADULT_ONLY, p, 3, {}, {}, visit_year=2026) > 0
    assert _ed_condition_weight("x", _ADULT_ONLY, p, 3, {}, {}, visit_year=2025) == 0.0


def test_newborn_ages_past_infancy() -> None:
    nb = _person(0, 2024)  # registered as a newborn, static age stays 0
    spec = {"min_age": 2, "probability": 0.1}
    assert _ed_condition_weight("x", spec, nb, 3, {}, {}, visit_year=2025) == 0.0
    assert _ed_condition_weight("x", spec, nb, 3, {}, {}, visit_year=2026) > 0


@pytest.mark.parametrize(("condition", "min_age"), sorted(_MIN_AGES.items()))
def test_protocol_declares_min_age(condition: str, min_age: int) -> None:
    assert load_encounter_condition(condition).get("min_age") == min_age
