"""Issue #3653: the well-child note of a child aged 3 or over records an
examination and a screening line, in en and ja, for each age band."""

from __future__ import annotations

import re
from datetime import date

import pytest

from clinosim.modules.document.narrative._visit_reason import load_visit_reason_soap
from tests.unit.modules.document.narrative.test_visit_reason_soap_3249 import _record, _soap

pytestmark = pytest.mark.unit

_JA = re.compile(r"[぀-ヿ一-鿿]")
# (age in years, visit date)
_AGES = [(3, date(2023, 1, 5)), (8, date(2018, 1, 5)), (15, date(2011, 1, 5))]


def _note(country: str, dob: date) -> dict[str, str]:
    record = _record(
        country=country,
        visit_type="pediatric_visit",
        condition="well_child_school",
        dx="Z00.129" if country == "US" else "Z00.1",
        chronic=[],
        age_dob=dob,
        when="2026-06-18T10:16:00",
        vitals={"heart_rate": 88, "temperature_celsius": 36.7, "systolic_bp": 100, "diastolic_bp": 62},
    )
    return _soap(record, country)


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize(("age", "dob"), _AGES)
def test_exam_and_screening_lines_for_each_age_band(country: str, age: int, dob: date) -> None:
    objective = _note(country, dob)["O"]
    exam, screening = ("Examination:", "Screening:") if country == "US" else ("診察:", "スクリーニング:")
    assert exam in objective, objective
    assert screening in objective, objective
    if country == "US":
        assert not _JA.search(objective)
    else:
        assert _JA.search(objective)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_infant_exam_is_not_changed_for_older_children(country: str) -> None:
    objective = _note(country, date(2018, 1, 5))["O"]
    assert "fontanelle" not in objective and "大泉門" not in objective


def test_exam_and_screening_tables_cover_every_age_from_3_years() -> None:
    from clinosim.age_bands import find_age_band

    data = load_visit_reason_soap().well_child
    for months in (36, 71, 72, 143, 144, 216, 300):
        assert find_age_band(data.exam, months) is not None, months
        assert find_age_band(data.screening, months) is not None, months
