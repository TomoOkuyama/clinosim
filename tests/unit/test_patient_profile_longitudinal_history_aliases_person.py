"""Cycle 2 H1 — PatientProfile.longitudinal_history must track PersonRecord.

The inpatient encounter CIF truncation bug (Issue #1735) traced to
`activator.py:853` — the activator shallow-copied `person.longitudinal_history`
into `PatientProfile`. Any subsequent `advance_one_year` call appended to
the person's list but the frozen cached profile stayed with its old
snapshot, so inpatient admit CIFs emitted a truncated history that
missed every post-admit year's Phase 4a/4b/4c trajectory data.

Fix: alias the list reference instead of copying. Verified here by
appending to `person.longitudinal_history` after activation and asserting
the profile sees the append — a shallow copy would fail this assertion.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.locale.loader import load_demographics
from clinosim.modules.longitudinal.engine import YearSnapshot
from clinosim.modules.patient.activator import activate_patient
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_DEMO = load_demographics("US")


def _person(start_history: list[YearSnapshot] | None = None) -> PersonRecord:
    p = PersonRecord(
        person_id="P-H1",
        household_id="H1",
        age=60,
        sex="M",
        date_of_birth=date(1964, 1, 1),
        chronic_conditions=["I10"],
    )
    p.longitudinal_history = list(start_history or [])
    return p


def test_patient_profile_longitudinal_history_tracks_subsequent_person_appends() -> None:
    """Activate at year 2024 with a 1-element history; append year 2025
    to the person; assert the profile sees the new entry (same list
    object, not a frozen copy)."""
    person = _person(start_history=[YearSnapshot(year=2024)])
    profile = activate_patient(person, np.random.default_rng(0), _DEMO, as_of_year=2024)
    assert len(profile.longitudinal_history) == 1
    person.longitudinal_history.append(YearSnapshot(year=2025))
    assert len(profile.longitudinal_history) == 2, (
        "profile.longitudinal_history is a frozen shallow copy — "
        "activator should alias the list reference so later advance_one_year "
        "appends propagate to the cached profile"
    )
    assert profile.longitudinal_history[-1].year == 2025


def test_patient_profile_longitudinal_history_tracks_full_sim_year_sequence() -> None:
    """End-to-end shape: activate at year 2024 (mid-sim admit), then run
    aging passes appending years 2025..2028. Final profile.longitudinal_history
    must carry [2024..2028], not the frozen [2024]."""
    person = _person(start_history=[YearSnapshot(year=2024)])
    profile = activate_patient(person, np.random.default_rng(1), _DEMO, as_of_year=2024)
    for year in (2025, 2026, 2027, 2028):
        person.longitudinal_history.append(YearSnapshot(year=year))
    years = [snap.year for snap in profile.longitudinal_history]
    assert years == [2024, 2025, 2026, 2027, 2028]
