"""Issue #1219: Encounter must survive the after-death filter for in-hospital deaths.

The `_drop_entries_after_death` bundle-level safety gate (Issue #926) used
`_AFTER_DEATH_ALLOWED_RESOURCE_TYPES = {"Patient"}`. Every other resource
type was field-checked via `_dt_fields`, which yields `period.end`. For
an in-hospital death, `Encounter.period.end = discharge_datetime`
(hospital's body-out timestamp) is legitimately after `date_of_death` —
so the whole Encounter was silently dropped, while its per-timestamp
children (Composition, DiagnosticReport, ServiceRequest, MR, MA,
Procedure, DocumentReference, ClinicalImpression with per-event
timestamps ≤ dod) survived, leaving dangling `encounter.reference` refs.

P=10000 s=1111 audit found 5 such IMP encounters silently dropped,
producing 41 dangling child-to-Encounter references. The synth-ED bridge
Encounter always survived (its `period.end = IMP admission_datetime`,
well before dod), producing an asymmetric "bridge present but IMP
dropped" shape.

The fix widens `_AFTER_DEATH_ALLOWED_RESOURCE_TYPES` to include
Encounter and other dimensional / lifecycle resources — mirroring
`_POST_SNAPSHOT_ALLOWED_RESOURCE_TYPES` (Issue #945).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4 import (
    _AFTER_DEATH_ALLOWED_RESOURCE_TYPES,
    _AFTER_DEATH_START_GATED_RESOURCE_TYPES,
    _drop_entries_after_death,
)

pytestmark = pytest.mark.unit


def _entry(resource: dict) -> dict:
    return {"resource": resource}


def test_encounter_with_period_end_after_death_survives() -> None:
    """The core case: IMP encounter with body-out timestamp after dod is kept."""
    encounter = {
        "resourceType": "Encounter",
        "id": "enc-imp-1",
        "status": "finished",
        "period": {"start": "2025-10-20T08:00:00", "end": "2025-10-27T14:00:00"},
    }
    kept = _drop_entries_after_death([_entry(encounter)], "2025-10-22")
    assert len(kept) == 1
    assert kept[0]["resource"]["id"] == "enc-imp-1"


def test_encounter_fully_before_death_still_survives() -> None:
    """Regression guard: encounter entirely before dod still passes (allowlist blanket)."""
    encounter = {
        "resourceType": "Encounter",
        "id": "enc-past-1",
        "period": {"start": "2025-08-01", "end": "2025-08-15"},
    }
    kept = _drop_entries_after_death([_entry(encounter)], "2025-10-22")
    assert len(kept) == 1


def test_coverage_with_period_end_after_death_survives() -> None:
    """Coverage's insurance-card end after dod is legitimate (Issue #944 status flip)."""
    coverage = {
        "resourceType": "Coverage",
        "id": "cov-1",
        "period": {"start": "2024-04-01", "end": "2026-03-31"},
    }
    kept = _drop_entries_after_death([_entry(coverage)], "2025-10-22")
    assert len(kept) == 1


def test_care_team_with_period_end_after_death_survives() -> None:
    care_team = {
        "resourceType": "CareTeam",
        "id": "ct-1",
        "period": {"start": "2025-10-20", "end": "2025-10-27"},
    }
    kept = _drop_entries_after_death([_entry(care_team)], "2025-10-22")
    assert len(kept) == 1


def test_practitioner_survives_regardless_of_dates() -> None:
    prac = {"resourceType": "Practitioner", "id": "dr-1"}
    kept = _drop_entries_after_death([_entry(prac)], "2025-10-22")
    assert len(kept) == 1


def test_observation_after_death_is_still_dropped() -> None:
    """Regression guard: event-timestamped resources still get gate-dropped (invariant)."""
    obs = {
        "resourceType": "Observation",
        "id": "obs-post-mortem",
        "status": "final",
        "effectiveDateTime": "2025-10-24T10:00:00",  # 2 days after death
        "code": {"text": "HR"},
        "valueQuantity": {"value": 80},
    }
    kept = _drop_entries_after_death([_entry(obs)], "2025-10-22")
    assert kept == []


def test_medication_admin_after_death_is_still_dropped() -> None:
    ma = {
        "resourceType": "MedicationAdministration",
        "id": "ma-post-mortem",
        "effectivePeriod": {"start": "2025-10-24T10:00:00"},
    }
    kept = _drop_entries_after_death([_entry(ma)], "2025-10-22")
    assert kept == []


def test_medication_admin_same_day_as_death_survives() -> None:
    """Regression guard: same-day terminal activity survives (Issue #926 invariant)."""
    ma = {
        "resourceType": "MedicationAdministration",
        "id": "ma-terminal",
        "effectivePeriod": {"start": "2025-10-22T05:00:00"},
    }
    kept = _drop_entries_after_death([_entry(ma)], "2025-10-22")
    assert len(kept) == 1


def test_allowlist_covers_expected_resource_types() -> None:
    """Both gates (blanket + start-gated) cover the same resource surface as
    the snapshot allowlist — activity resources fall through to field-check.
    """
    from clinosim.modules.output.fhir_r4 import _POST_SNAPSHOT_ALLOWED_RESOURCE_TYPES

    union = _AFTER_DEATH_ALLOWED_RESOURCE_TYPES | _AFTER_DEATH_START_GATED_RESOURCE_TYPES
    assert union == _POST_SNAPSHOT_ALLOWED_RESOURCE_TYPES


def test_encounter_starting_after_death_is_still_dropped() -> None:
    """Regression guard for Issue #926: bogus admission-after-death is dropped."""
    encounter = {
        "resourceType": "Encounter",
        "id": "enc-bogus",
        "period": {"start": "2026-07-20T10:54:00+09:00", "end": "2026-08-03T20:14:00+09:00"},
    }
    kept = _drop_entries_after_death([_entry(encounter)], "2025-12-16")
    assert kept == [], "post-death admission Encounter must be dropped"


def test_coverage_starting_after_death_is_still_dropped() -> None:
    coverage = {
        "resourceType": "Coverage",
        "id": "cov-bogus",
        "period": {"start": "2026-01-01", "end": "2027-03-31"},
    }
    kept = _drop_entries_after_death([_entry(coverage)], "2025-12-16")
    assert kept == []
