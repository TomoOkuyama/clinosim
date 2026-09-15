"""Issue #926: `_drop_entries_after_death` bundle-level safety gate.

This is the belt-and-braces filter for the giant `pt-5d9ec536bb1d` case
(v0.5.0 p=10000): a full 12-day inpatient episode 7 months post-mortem
plus 9 post-mortem Immunizations and one post-mortem Procedure — 1,869
after-death events in total across 9 resource types. The generator-side
gate for immunizations is patched at the enricher; this file locks down
the universal fallback that also catches the giant-encounter case
(whose slow / rare root path the p=1000 regression cannot see).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4 import _drop_entries_after_death

pytestmark = pytest.mark.unit


def _entry(resource: dict) -> dict:
    return {"fullUrl": f"urn:uuid:{resource.get('id', 'x')}", "resource": resource}


def test_drops_encounter_starting_after_death() -> None:
    entries = [
        _entry(
            {
                "resourceType": "Encounter",
                "id": "enc-after",
                "period": {"start": "2026-07-20T10:54:00+09:00", "end": "2026-08-03T20:14:00+09:00"},
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2025-12-16")
    assert kept == [], "post-death Encounter must be dropped"


def test_keeps_encounter_before_death() -> None:
    entries = [
        _entry(
            {
                "resourceType": "Encounter",
                "id": "enc-before",
                "period": {"start": "2025-12-01T09:00:00+09:00", "end": "2025-12-16T04:30:00+09:00"},
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2025-12-16")
    assert len(kept) == 1


def test_keeps_same_day_activity() -> None:
    """Same-day activity survives (final labs, terminal MAR, death
    certificate all legitimately land on the day of death)."""
    entries = [
        _entry(
            {
                "resourceType": "MedicationAdministration",
                "id": "mar-terminal",
                "effectiveDateTime": "2025-12-16T04:29:00+09:00",
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2025-12-16")
    assert len(kept) == 1


def test_patient_resource_always_kept() -> None:
    """Patient itself carries deceasedDateTime and must survive the
    filter regardless of when its own fields fall."""
    entries = [
        _entry(
            {
                "resourceType": "Patient",
                "id": "pt-1",
                "deceasedDateTime": "2025-12-16",
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2025-12-16")
    assert len(kept) == 1


def test_drops_immunization_after_death() -> None:
    entries = [
        _entry(
            {
                "resourceType": "Immunization",
                "id": "imm-after",
                "occurrenceDateTime": "2025-11-01",
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2025-10-05")
    assert kept == []


def test_drops_bundle_of_after_death_resources_wholesale() -> None:
    """The giant `pt-5d9ec536bb1d` case: an entire encounter's worth of
    resources (Encounter + MedRequest + MedAdmin + Observation +
    Procedure + DiagnosticReport + ImagingStudy + ServiceRequest) all
    timestamped 7 months after death. The whole batch must drop."""
    types_and_dt_fields = [
        ("Encounter", {"period": {"start": "2026-07-20T10:54:00+09:00", "end": "2026-08-03T20:14:00+09:00"}}),
        ("MedicationRequest", {"authoredOn": "2026-07-20T15:24:00+09:00"}),
        ("MedicationAdministration", {"effectiveDateTime": "2026-07-21T08:00:00+09:00"}),
        ("Observation", {"effectiveDateTime": "2026-07-20T11:00:00+09:00"}),
        ("Procedure", {"performedDateTime": "2026-07-20T14:55:00+09:00"}),
        ("DiagnosticReport", {"issued": "2026-07-20T16:00:00+09:00"}),
        ("ImagingStudy", {"started": "2026-07-20T14:39:00+09:00"}),
        ("ServiceRequest", {"occurrenceDateTime": "2026-07-20T15:24:00+09:00"}),
    ]
    entries = [_entry({"resourceType": rt, "id": rt.lower() + "-x", **fields}) for rt, fields in types_and_dt_fields]
    kept = _drop_entries_after_death(entries, "2025-12-16")
    assert kept == [], f"expected all 8 resources dropped, kept={kept}"


def test_keeps_resource_with_no_dt_fields() -> None:
    """A resource that doesn't have any of the gating dateTime fields
    survives (nothing to compare — the filter is silent on it)."""
    entries = [_entry({"resourceType": "Coverage", "id": "cov-x", "status": "active"})]
    kept = _drop_entries_after_death(entries, "2025-12-16")
    assert len(kept) == 1


# ----- Encounter.period.end clamp on death (Issue #1442) -----
#
# `_drop_entries_after_death` used to gate Encounter on `period.start`
# only, letting `period.end` legitimately extend past dod for in-hospital
# deaths (Issue #1219 comment). That reasoning holds for `disp=exp`
# encounters where the discharge event IS the death. It fails for
# `disp=home` encounters whose LOS-driven discharge date happens to
# overshoot the actuarial death date — the sim then emits a live
# discharge on a day the patient is already dead. Mirror the Coverage
# sibling: clamp `period.end` down to dod and flip `dischargeDisposition`
# to `exp` so the resource's active period ends at the death event.


def test_encounter_clamps_period_end_when_home_disp_extends_past_death() -> None:
    """Encounter that started before death and would have discharged
    home 6 days later must be clamped: period.end = dod, disp flipped
    to exp. Mirrors the Coverage branch (period.end clamp + status flip)."""
    entries = [
        _entry(
            {
                "resourceType": "Encounter",
                "id": "enc-clamp",
                "period": {"start": "2026-01-05T08:06:00Z", "end": "2026-01-15T12:06:00Z"},
                "hospitalization": {
                    "dischargeDisposition": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/discharge-disposition",
                                "code": "home",
                            }
                        ]
                    }
                },
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2026-01-09")
    assert len(kept) == 1
    enc = kept[0]["resource"]
    # period.end clamped down to dod (calendar-date prefix)
    assert enc["period"]["end"] == "2026-01-09"
    # dischargeDisposition flipped from home → exp
    disp_code = enc["hospitalization"]["dischargeDisposition"]["coding"][0]["code"]
    assert disp_code == "exp"


def test_encounter_leaves_exp_disp_alone_but_still_clamps_end() -> None:
    """When the disposition is already `exp` (in-hospital death was
    recorded correctly), the disp field must not be double-flipped, but
    the clamp still fires — a same-day death encounter that landed on
    `T23:37+09` (24 min past the dod-midnight ceiling on some checks)
    should not encode as post-death by strict datetime compare either."""
    entries = [
        _entry(
            {
                "resourceType": "Encounter",
                "id": "enc-exp",
                "period": {"start": "2026-01-05T08:06:00Z", "end": "2026-01-15T12:06:00Z"},
                "hospitalization": {
                    "dischargeDisposition": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/discharge-disposition",
                                "code": "exp",
                            }
                        ]
                    }
                },
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2026-01-09")
    enc = kept[0]["resource"]
    assert enc["period"]["end"] == "2026-01-09"
    # disp untouched — already exp
    disp_code = enc["hospitalization"]["dischargeDisposition"]["coding"][0]["code"]
    assert disp_code == "exp"


def test_encounter_period_end_before_dod_untouched() -> None:
    """An encounter whose period.end already sits at or before dod
    must be forwarded unchanged — no spurious clamp, no disp flip."""
    entries = [
        _entry(
            {
                "resourceType": "Encounter",
                "id": "enc-before-dod",
                "period": {"start": "2026-01-05T08:06:00Z", "end": "2026-01-08T20:00:00Z"},
                "hospitalization": {
                    "dischargeDisposition": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/discharge-disposition",
                                "code": "home",
                            }
                        ]
                    }
                },
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2026-01-09")
    enc = kept[0]["resource"]
    # period.end intact
    assert enc["period"]["end"] == "2026-01-08T20:00:00Z"
    # disp intact
    disp_code = enc["hospitalization"]["dischargeDisposition"]["coding"][0]["code"]
    assert disp_code == "home"


def test_encounter_without_disp_still_clamps_end() -> None:
    """An encounter without dischargeDisposition (legitimate for open
    admissions) must still have period.end clamped. No disp field to
    flip."""
    entries = [
        _entry(
            {
                "resourceType": "Encounter",
                "id": "enc-no-disp",
                "period": {"start": "2026-01-05T08:06:00Z", "end": "2026-01-15T12:06:00Z"},
            }
        )
    ]
    kept = _drop_entries_after_death(entries, "2026-01-09")
    enc = kept[0]["resource"]
    assert enc["period"]["end"] == "2026-01-09"
