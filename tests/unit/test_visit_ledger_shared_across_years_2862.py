"""One outpatient visit ledger per person across the per-year profiles (Issue #2862).

The patient cache holds one ``PatientProfile`` per (person, year). The
outpatient ledger that records ``baseline_only`` procedures lived only on
the profile, so it restarted every year and a one-shot procedure
(polysomnography) fired once per year.
"""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.locale.loader import load_demographics
from clinosim.simulator._setup import _activate_cached_person
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _person() -> PersonRecord:
    return PersonRecord(person_id="POP-000001", household_id="HH-1", age=60, sex="M", date_of_birth=date(1965, 5, 1))


def test_profiles_of_different_years_share_the_person_ledger() -> None:
    person = _person()
    cache: dict = {}
    demo = load_demographics("US")
    p2024 = _activate_cached_person(person, as_of_year=2024, patient_cache=cache, master_seed=1, demo=demo)
    p2025 = _activate_cached_person(person, as_of_year=2025, patient_cache=cache, master_seed=1, demo=demo)
    assert p2024 is not p2025
    p2024.visit_ledger.baseline_procedures.add("60554003")
    assert "60554003" in p2025.visit_ledger.baseline_procedures
    assert p2025.visit_ledger is person.visit_ledger
