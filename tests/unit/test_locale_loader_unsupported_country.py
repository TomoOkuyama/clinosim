"""Locale-loader unsupported-country contract must be consistent across modules.

care_level's `load_rates()` is the compliant precedent: unsupported countries
return `{}` rather than silently falling back to US data. immunization/
code_status/family_history previously fell back to US for ANY country other
than JP, which would silently serve the wrong locale's data if a third
country were ever added (2026-07-02 grand design review finding).
"""

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("country", ["DE", "FR", "unknown", ""])
def test_immunization_schedule_empty_for_unsupported_country(country):
    from clinosim.modules.immunization.engine import load_schedule

    assert load_schedule(country) == {}


@pytest.mark.parametrize("country", ["DE", "FR", "unknown", ""])
def test_code_status_rates_empty_for_unsupported_country(country):
    from clinosim.modules.code_status.engine import load_rates

    assert load_rates(country) == {}


@pytest.mark.parametrize("country", ["DE", "FR", "unknown", ""])
def test_family_history_prevalence_empty_for_unsupported_country(country):
    from clinosim.modules.family_history.engine import load_prevalence

    assert load_prevalence(country) == {}


def test_immunization_schedule_still_populated_for_us_and_jp():
    from clinosim.modules.immunization.engine import load_schedule

    assert load_schedule("US") != {}
    assert load_schedule("JP") != {}


def test_code_status_rates_still_populated_for_us_and_jp():
    from clinosim.modules.code_status.engine import load_rates

    assert load_rates("US") != {}
    assert load_rates("JP") != {}


def test_family_history_prevalence_still_populated_for_us_and_jp():
    from clinosim.modules.family_history.engine import load_prevalence

    assert load_prevalence("US") != {}
    assert load_prevalence("JP") != {}
