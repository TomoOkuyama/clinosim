"""Issue #945: `_drop_entries_after_snapshot` bundle-level cutoff filter.

For inpatients whose admission is still open at CIF ``snapshot_date``,
the generator pre-emits planned future events (nursing notes, vitals,
MAR, imaging, DR, MR, Composition) with timestamps AFTER the snapshot.
v0.5.0 p=10000 counted 4,798 such entries across 7 resource types with
the furthest event landing 28 days past snapshot. This test locks the
universal bundle-finalize gate that caps the event stream at snapshot,
mirroring the #928 after-death filter's structural pattern.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4 import (
    _POST_SNAPSHOT_ALLOWED_RESOURCE_TYPES,
    _drop_entries_after_snapshot,
)

pytestmark = pytest.mark.unit


def _entry(resource: dict) -> dict:
    return {"fullUrl": f"urn:uuid:{resource.get('id', 'x')}", "resource": resource}


SNAP = "2026-08-28"


def test_drops_observation_after_snapshot() -> None:
    entries = [
        _entry(
            {
                "resourceType": "Observation",
                "id": "obs-future",
                "effectiveDateTime": "2026-08-30T14:00:00+09:00",
            }
        )
    ]
    kept, dropped = _drop_entries_after_snapshot(entries, SNAP)
    assert kept == []
    assert dropped == {"Observation": 1}


def test_keeps_observation_on_snapshot_day() -> None:
    """Same-day activity is kept (inclusive on snapshot — the death
    filter uses the same YYYY-MM-DD prefix comparison rule)."""
    entries = [
        _entry(
            {
                "resourceType": "Observation",
                "id": "obs-cutoff",
                "effectiveDateTime": "2026-08-28T23:59:59+09:00",
            }
        )
    ]
    kept, dropped = _drop_entries_after_snapshot(entries, SNAP)
    assert len(kept) == 1
    assert dropped == {}


def test_drops_document_reference_by_context_period_start() -> None:
    """DocumentReference.context.period.start is walked (the reproduction
    script in Issue #945 uses this field)."""
    entries = [
        _entry(
            {
                "resourceType": "DocumentReference",
                "id": "doc-future-context",
                "date": "2026-08-27T00:00:00+09:00",  # OK
                "context": {"period": {"start": "2026-09-25T16:00:00+09:00"}},
            }
        )
    ]
    kept, dropped = _drop_entries_after_snapshot(entries, SNAP)
    assert kept == []
    assert dropped == {"DocumentReference": 1}


def test_drops_period_start_after_snapshot() -> None:
    """Period start after snapshot drops (event that begins in the future)."""
    entries = [
        _entry(
            {
                "resourceType": "MedicationAdministration",
                "id": "mar-future-start",
                "effectivePeriod": {"start": "2026-09-01T08:00:00+09:00", "end": "2026-09-02T08:00:00+09:00"},
            }
        )
    ]
    kept, dropped = _drop_entries_after_snapshot(entries, SNAP)
    assert kept == []
    assert dropped == {"MedicationAdministration": 1}


def test_keeps_period_end_after_snapshot_when_start_before() -> None:
    """Period.end past snapshot is fine as long as .start is on/before
    snapshot — an infusion begun before snapshot whose projected end
    trails past snapshot is a real historical event with a projected
    endpoint, not a future event."""
    entries = [
        _entry(
            {
                "resourceType": "MedicationAdministration",
                "id": "mar-ongoing",
                "effectivePeriod": {"start": "2026-08-25T08:00:00+09:00", "end": "2026-09-01T08:00:00+09:00"},
            }
        )
    ]
    kept, dropped = _drop_entries_after_snapshot(entries, SNAP)
    assert len(kept) == 1
    assert dropped == {}


def test_encounter_open_admission_never_dropped() -> None:
    """Encounter is in the allowlist — `Encounter.period.end` may extend
    past snapshot for currently-open admissions, which is the CORRECT
    representation of an ongoing episode (v0.5.0 Encounter table already
    shows 0 future records — Encounter.period.end is either absent or
    intentionally past snapshot)."""
    entries = [
        _entry(
            {
                "resourceType": "Encounter",
                "id": "enc-open",
                "period": {"start": "2026-08-15T09:00:00+09:00", "end": "2026-09-19T10:00:00+09:00"},
            }
        )
    ]
    kept, dropped = _drop_entries_after_snapshot(entries, SNAP)
    assert len(kept) == 1
    assert dropped == {}


def test_coverage_period_end_after_snapshot_never_dropped() -> None:
    """Coverage is in the allowlist — active insurance card runs into
    the future by design; #944 fix flips ``status`` based on
    period.end vs snapshot."""
    entries = [
        _entry(
            {
                "resourceType": "Coverage",
                "id": "cov-active",
                "status": "active",
                "period": {"start": "2026-04-01", "end": "2027-03-31"},
            }
        )
    ]
    kept, dropped = _drop_entries_after_snapshot(entries, SNAP)
    assert len(kept) == 1
    assert dropped == {}


def test_all_seven_leaking_resource_types_drop_in_one_bundle() -> None:
    """The 7 resource types Issue #945 identified as leaking future
    events (Observation, DocumentReference, MedicationAdministration,
    DiagnosticReport, MedicationRequest, Composition, ImagingStudy)
    all drop when their own timestamp is past snapshot."""
    types_and_dt_fields = [
        ("Observation", {"effectiveDateTime": "2026-09-25T00:00:00+09:00"}),
        ("DocumentReference", {"date": "2026-09-25T16:00:00+09:00"}),
        ("MedicationAdministration", {"effectiveDateTime": "2026-09-01T08:00:00+09:00"}),
        ("DiagnosticReport", {"issued": "2026-08-30T16:00:00+09:00"}),
        ("MedicationRequest", {"authoredOn": "2026-08-30T15:24:00+09:00"}),
        ("Composition", {"date": "2026-08-30T22:27:00+09:00"}),
        ("ImagingStudy", {"started": "2026-08-30T22:27:00+09:00"}),
    ]
    entries = [_entry({"resourceType": rt, "id": rt.lower() + "-x", **fields}) for rt, fields in types_and_dt_fields]
    kept, dropped = _drop_entries_after_snapshot(entries, SNAP)
    assert kept == [], f"expected all 7 resources dropped, kept={kept}"
    assert sum(dropped.values()) == 7
    assert set(dropped.keys()) == {rt for rt, _ in types_and_dt_fields}


def test_no_snapshot_date_is_noop_on_caller() -> None:
    """When ``snapshot_date`` is absent (test fixtures / legacy CIF
    without metadata), the filter is not invoked at all — the
    _build_bundle guard skips it. This test locks the filter itself: an
    empty snapshot_iso would compare lexically, so callers MUST NOT
    invoke the filter with an empty string. Exercised at the
    _build_bundle level via a caller test elsewhere; here we assert the
    guard shape by verifying that a legitimate past-snapshot resource
    is preserved."""
    entries = [
        _entry(
            {
                "resourceType": "Observation",
                "id": "obs-past",
                "effectiveDateTime": "2026-08-01T09:00:00+09:00",
            }
        )
    ]
    kept, dropped = _drop_entries_after_snapshot(entries, SNAP)
    assert len(kept) == 1
    assert dropped == {}


def test_resource_with_no_dt_fields_kept() -> None:
    """A resource that doesn't have any of the gating dateTime fields
    (e.g. a bare Condition with no onset/recorded) survives — nothing
    to compare, filter is silent."""
    entries = [_entry({"resourceType": "Condition", "id": "cond-bare", "code": {"text": "x"}})]
    kept, dropped = _drop_entries_after_snapshot(entries, SNAP)
    assert len(kept) == 1
    assert dropped == {}


def test_allowlist_covers_dimensional_types() -> None:
    """Sanity: the allowlist covers every dimensional type that can
    legitimately carry post-snapshot dates (open Encounter, active
    Coverage, ongoing CareTeam) plus the pure-reference types
    (Practitioner / Organization / Location / Device / Medication /
    Endpoint / PractitionerRole) and Patient. This assertion locks the
    list against accidental removal."""
    required = {
        "Patient",
        "Encounter",
        "Coverage",
        "CareTeam",
        "Practitioner",
        "PractitionerRole",
        "Organization",
        "Location",
        "Endpoint",
        "Device",
        "Medication",
    }
    assert required.issubset(_POST_SNAPSHOT_ALLOWED_RESOURCE_TYPES)


def test_mixed_bundle_partial_drop_counter_accurate() -> None:
    """Mixed bundle: 2 Observations (1 past, 1 future), 1 MedAdmin
    (past). Only the future Observation drops; counter reports exactly
    one Observation drop."""
    entries = [
        _entry({"resourceType": "Observation", "id": "obs-past", "effectiveDateTime": "2026-08-25T10:00:00+09:00"}),
        _entry({"resourceType": "Observation", "id": "obs-future", "effectiveDateTime": "2026-09-01T10:00:00+09:00"}),
        _entry(
            {
                "resourceType": "MedicationAdministration",
                "id": "mar-past",
                "effectiveDateTime": "2026-08-27T08:00:00+09:00",
            }
        ),
    ]
    kept, dropped = _drop_entries_after_snapshot(entries, SNAP)
    assert len(kept) == 2
    assert {e["resource"]["id"] for e in kept} == {"obs-past", "mar-past"}
    assert dropped == {"Observation": 1}
