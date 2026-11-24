"""Issue #3651: a paediatric acute-illness note states symptoms and examination
findings, and names an antipyretic only with a dose (none is ordered, so none)."""

from __future__ import annotations

import re
from datetime import date

import pytest

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative._visit_reason import load_visit_reason_soap
from tests.unit.modules.document.narrative.test_visit_reason_soap_3249 import _record, _soap

pytestmark = pytest.mark.unit

# visit condition -> (ICD-10-CM / ICD-10 code of the visit, date of birth)
_CASES = {
    "pediatric_uri": ("J06.9", date(2018, 5, 1)),
    "pediatric_otitis_media": ("H66.90", date(2024, 5, 1)),
    "pediatric_bronchiolitis": ("J21.9", date(2026, 1, 1)),
    "pediatric_injury": ("S93.40", date(2016, 5, 1)),
}
_JA = re.compile(r"[぀-ヿ一-鿿]")


def _note(country: str, condition: str, temp: float = 36.8) -> dict[str, str]:
    dx, dob = _CASES[condition]
    record = _record(
        country=country,
        visit_type="pediatric_visit",
        condition=condition,
        dx=dx,
        chronic=[],
        age_dob=dob,
        when="2026-05-12T10:05:00",
        vitals={"heart_rate": 100, "temperature_celsius": temp},
    )
    return _soap(record, country)


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("condition", sorted(_CASES))
def test_subjective_and_objective_are_not_the_fallback(country: str, condition: str) -> None:
    lang = "en" if country == "US" else "ja"
    soap = _note(country, condition)
    fallback = t("fallback.generic_fallback", lang)
    assert fallback not in soap["O"]
    assert soap["O"].strip() != fallback
    symptoms = load_visit_reason_soap().conditions[condition].subjective[0]
    assert symptoms[lang] in soap["S"]
    assert load_visit_reason_soap().conditions[condition].objective[0][lang] in soap["O"]
    if lang == "ja":
        assert _JA.search(soap["O"]) and _JA.search(soap["S"])
    else:
        assert not _JA.search(soap["O"]) and not _JA.search(soap["S"])


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("condition", sorted(_CASES))
def test_plan_names_no_antipyretic_without_a_dose(country: str, condition: str) -> None:
    for temp in (36.8, 38.9):
        plan = _note(country, condition, temp)["P"]
        assert not re.search(r"antipyretic|解熱薬|解熱剤", plan, re.IGNORECASE), plan


def test_fever_is_claimed_only_when_the_visit_is_febrile() -> None:
    for condition in _CASES:
        afebrile = _note("US", condition, 36.8)
        assert "Fever:" not in afebrile["A"] and "Fever:" not in afebrile["P"]
        # No fever is asserted in the symptoms or the findings either.
        assert not re.search(r"\bfever\b", afebrile["S"] + afebrile["O"], re.IGNORECASE)
    assert "Fever:" in _note("US", "pediatric_uri", 38.9)["A"]


def test_every_scheduled_acute_condition_has_findings() -> None:
    from clinosim.modules.pediatric.calendar import _load_schedule

    presented = set(_load_schedule().presentations)
    assert presented, "no presentation block"
    conditions = load_visit_reason_soap().conditions
    for cid in presented:
        lines = conditions.get(cid)
        assert lines is not None, cid
        assert lines.subjective and lines.objective, cid
