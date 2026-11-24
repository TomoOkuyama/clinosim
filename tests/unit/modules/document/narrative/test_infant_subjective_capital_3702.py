"""The outpatient Subjective of an infant names the child's age and starts with
a capital letter (Issue #3702): an age of 0 years is a valid age, not a missing
one."""

from __future__ import annotations

from datetime import date

import pytest

from tests.unit.modules.document.narrative.test_visit_reason_soap_3249 import _record, _soap

pytestmark = pytest.mark.unit


def _subjective(country: str, dob: date, when: str, *, condition: str = "immunization_infant") -> str:
    record = _record(
        country=country,
        visit_type="pediatric_visit" if condition else "",
        condition=condition,
        dx="Z23",
        chronic=[],
        age_dob=dob,
        when=when,
    )
    return _soap(record, country)["S"]


def test_infant_en_renders_an_age_phrase_and_a_capital() -> None:
    s = _subjective("US", date(2026, 3, 20), "2026-07-22T10:02:00")
    assert s.startswith("4-month-old female patient presenting for"), s


def test_newborn_en() -> None:
    s = _subjective("US", date(2026, 7, 10), "2026-07-22T10:02:00")
    assert s.startswith("Newborn female patient presenting for"), s


def test_infant_ja_has_a_natural_age_phrase() -> None:
    s = _subjective("JP", date(2026, 3, 20), "2026-07-22T10:02:00")
    assert s.startswith("生後4か月の乳児 (女性)、"), s


def test_one_year_and_older_is_unchanged() -> None:
    s = _subjective("US", date(2024, 1, 5), "2026-07-22T10:02:00")
    assert s.startswith("2-year-old female patient presenting for"), s


def test_first_letter_is_capital_without_a_known_age() -> None:
    record = _record(country="US", visit_type="", condition="", dx="Z23", chronic=[], age_dob=date(2026, 3, 20))
    record["patient"].pop("date_of_birth")
    record["patient"]["age"] = 0
    s = _soap(record, "US")["S"]
    assert s[0].isupper(), s
