"""Issue #3566: infant outpatient notes state growth once and carry feeding,
development and an examination statement at well-child and catch-up
vaccination visits."""

from __future__ import annotations

from datetime import date

import pytest

from tests.unit.modules.document.narrative.test_visit_reason_soap_3249 import _imm, _record, _soap

pytestmark = pytest.mark.unit

_VITALS = {"heart_rate": 131, "temperature_celsius": 36.9}
_DOB = date(2026, 3, 20)
_WHEN = "2026-07-22T10:02:00"


def _infant(country: str, condition: str, *, vaccine: bool, visit_type: str = "pediatric_visit") -> dict[str, str]:
    imms = [{**_imm("10", 2, "L1"), "occurrence_date": _WHEN[:10]}] if vaccine else []
    record = _record(
        country=country,
        visit_type=visit_type if condition else "",
        condition=condition,
        dx="Z23" if vaccine and "well" not in condition else ("Z00.129" if country == "US" else "Z00.1"),
        chronic=[],
        age_dob=_DOB,
        when=_WHEN,
        vitals=_VITALS,
        immunizations=imms,
    )
    return _soap(record, country)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_growth_is_stated_once_when_vaccination_and_well_child_share_a_visit(country: str) -> None:
    objective = _infant(country, "well_child_infant", vaccine=True)["O"]
    marker = "Growth:" if country == "US" else "身体計測:"
    assert objective.count(marker) == 1


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("condition", ["well_child_infant", "immunization_infant", ""])
def test_infant_visits_have_feeding_development_and_exam(country: str, condition: str) -> None:
    vaccine = condition != "well_child_infant"
    soap = _infant(country, condition, vaccine=vaccine)
    feeding, exam, dev = ("Feeding", "Examination", "development") if country == "US" else ("栄養", "診察", "発達")
    assert feeding in soap["S"]
    assert exam in soap["O"]
    assert dev in soap["A"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_older_child_vaccination_visit_gets_no_infant_block(country: str) -> None:
    record = _record(
        country=country,
        visit_type="pediatric_visit",
        condition="immunization_kindergarten",
        dx="Z23",
        chronic=[],
        age_dob=date(2021, 9, 25),
        when="2026-09-25T10:23:00",
        vitals=_VITALS,
        immunizations=[_imm("10", 4, "L1")],
    )
    soap = _soap(record, country)
    assert "fontanelle" not in soap["O"] and "大泉門" not in soap["O"]
