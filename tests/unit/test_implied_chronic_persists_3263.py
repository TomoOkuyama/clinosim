"""Issue #3263: a chronic condition a stay implies stays on the person's
problem list at later encounters, and is implied only for the share of
patients the epidemiology supports."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.simulator.helpers import _persist_implied_chronic
from clinosim.simulator.implied_chronic import _prevalence, implied_chronic_codes_to_add
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _person(pid: str) -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="H",
        age=75,
        sex="M",
        date_of_birth=date(1950, 1, 1),
        chronic_conditions=["E78"],
    )


def _record() -> SimpleNamespace:
    return SimpleNamespace(encounters=[SimpleNamespace(admission_datetime=datetime(2025, 5, 1, 9))])


def test_prevalence_is_configured_for_stroke_af_and_af_hf() -> None:
    assert 0.0 < _prevalence()["cerebral_infarction"]["I48"] < 1.0
    assert 0.0 < _prevalence()["atrial_fibrillation_rvr"]["I50"] < 1.0


def test_unlisted_implied_codes_stay_deterministic() -> None:
    codes = implied_chronic_codes_to_add("acute_mi", patient_id="P1", sex="M", age=70, have_bases=set())
    assert codes == ["I25", "I10", "E78"]


def test_stroke_af_share_matches_prevalence() -> None:
    n = 4000
    hits = sum(
        "I48"
        in implied_chronic_codes_to_add("cerebral_infarction", patient_id=f"POP-{i}", sex="M", age=70, have_bases=set())
        for i in range(n)
    )
    assert abs(hits / n - _prevalence()["cerebral_infarction"]["I48"]) < 0.03


def test_the_draw_is_stable_per_patient() -> None:
    a = implied_chronic_codes_to_add("cerebral_infarction", patient_id="POP-9", sex="F", age=70, have_bases=set())
    b = implied_chronic_codes_to_add("cerebral_infarction", patient_id="POP-9", sex="F", age=70, have_bases=set())
    assert a == b


def test_an_implied_code_is_kept_on_the_person_for_later_encounters() -> None:
    person = _person("POP-3263")
    _persist_implied_chronic(person, _record(), "acute_mi")  # type: ignore[arg-type]
    assert {"I25", "I10"} <= {c.split(".")[0] for c in person.chronic_conditions}
    assert person.chronic_onset["I25"] < date(2025, 5, 1)
    before = list(person.chronic_conditions)
    _persist_implied_chronic(person, _record(), "acute_mi")  # type: ignore[arg-type]
    assert person.chronic_conditions == before
