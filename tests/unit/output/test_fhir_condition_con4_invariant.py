"""Unit tests for FHIR R4 Condition con-4 invariant fix (Chain F, session 57).

FHIR R4 Condition.con-4 invariant requires:
  "If clinicalStatus='active', then abatementDateTime must NOT be present."

Session 57 Chain F fixed the bug where chronic-primary encounters received both
`clinicalStatus="active"` and `abatementDateTime`, violating con-4 on 2,452
resources. The fix restricts abatement emission to non-chronic-primary encounters.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from clinosim.modules.output._fhir_conditions import _build_conditions


def _make_ctx(
    discharge_dt: str | None = None,
    encounter_type: str = "inpatient",
    status: str = "completed",
    is_chronic_primary: bool = False,
    patient_id: str = "pt-123",
    country: str = "US",
) -> dict:
    """Minimal CIF record for condition building."""
    chronic_conditions = []
    if is_chronic_primary:
        # E11 = Type 2 Diabetes, a chronic primary code
        chronic_conditions = [
            {
                "code": "E11.9",
                "onset_date": "2020-01-15",
                "severity": "",
                "stage": "",
            }
        ]

    return {
        "patient": {
            "patient_id": patient_id,
            "chronic_conditions": chronic_conditions,
        },
        "clinical_diagnosis": {
            "admission_diagnosis_code": "E11.9" if is_chronic_primary else "J18.9",
            "discharge_diagnosis_code": "",
        },
        "encounters": [
            {
                "encounter_id": "enc-1",
                "encounter_type": encounter_type,
                "status": status,
                "admission_datetime": "2026-01-01T10:00:00Z",
                "discharge_datetime": discharge_dt,
                "attending_physician_id": "dr-001",
                "severity": "",
            }
        ],
        "deceased": False,
    }


def test_chronic_primary_active_no_abatement():
    """Chronic primary (E11) should have clinicalStatus='active' WITHOUT abatementDateTime.

    Even if the encounter is completed with discharge_datetime, a chronic
    primary diagnosis (e.g., E11 routine diabetes follow-up) is ongoing,
    not resolved — so it gets active status and NO abatement.
    """
    record = _make_ctx(discharge_dt="2026-01-05T15:00:00Z", is_chronic_primary=True)
    conditions = _build_conditions(record, patient_id="pt-123", country="US")

    # Should have 1 primary diagnosis condition (E11.9)
    assert len(conditions) == 1
    cond = conditions[0]

    # Verify con-4 compliance: active status WITHOUT abatement
    clinical_status = cond["clinicalStatus"]["coding"][0]["code"]
    assert clinical_status == "active", (
        f"Chronic primary should be active; got {clinical_status}"
    )
    assert "abatementDateTime" not in cond, (
        "Chronic primary should NOT have abatementDateTime (violates con-4)"
    )


def test_non_chronic_primary_completed_has_abatement():
    """Non-chronic primary (J18 pneumonia) completed encounter should have abatementDateTime.

    Acute conditions (non-chronic-primary) that complete should emit
    abatementDateTime at discharge and clinicalStatus='resolved'.
    """
    record = _make_ctx(
        discharge_dt="2026-01-05T15:00:00Z",
        encounter_type="inpatient",
        status="completed",
        is_chronic_primary=False,
    )
    conditions = _build_conditions(record, patient_id="pt-123", country="US")

    # Should have 1 primary diagnosis condition (J18.9)
    assert len(conditions) == 1
    cond = conditions[0]

    # Verify con-4 compliance: if abatement is present, status should NOT be active
    clinical_status = cond["clinicalStatus"]["coding"][0]["code"]
    assert "abatementDateTime" in cond, (
        "Non-chronic primary completed encounter should have abatementDateTime"
    )
    # When abatement is present, clinicalStatus must be resolved (or inactive, remission)
    assert clinical_status == "resolved", (
        f"Acute primary with abatement should be resolved; got {clinical_status}"
    )


def test_non_chronic_primary_in_progress_no_abatement():
    """Non-chronic primary in-progress encounter (no discharge) should have NO abatementDateTime.

    An acute encounter that is still in-progress (no discharge_datetime) should
    have clinicalStatus='active' and NO abatement.
    """
    record = _make_ctx(
        discharge_dt=None,
        encounter_type="inpatient",
        status="in-progress",
        is_chronic_primary=False,
    )
    conditions = _build_conditions(record, patient_id="pt-123", country="US")

    assert len(conditions) == 1
    cond = conditions[0]

    # In-progress acute should be active WITHOUT abatement
    clinical_status = cond["clinicalStatus"]["coding"][0]["code"]
    assert clinical_status == "active", (
        f"In-progress acute should be active; got {clinical_status}"
    )
    assert "abatementDateTime" not in cond, (
        "In-progress encounter should NOT have abatementDateTime"
    )


def test_outpatient_encounter_resolved_no_abatement():
    """Outpatient encounters always resolve (not chronic-primary).

    Outpatient visits are NOT chronic-primary; they resolve at completion.
    However, outpatient visits don't carry discharge_datetime in the normal
    flow (they're same-day), so abatement is not emitted.
    """
    record = _make_ctx(
        discharge_dt=None,  # Outpatient, no discharge datetime
        encounter_type="outpatient",
        status="completed",
        is_chronic_primary=False,
    )
    conditions = _build_conditions(record, patient_id="pt-123", country="US")

    assert len(conditions) == 1
    cond = conditions[0]

    # Outpatient is resolved by default, and no abatement because discharge_dt is None
    clinical_status = cond["clinicalStatus"]["coding"][0]["code"]
    assert clinical_status == "resolved", (
        f"Outpatient should be resolved; got {clinical_status}"
    )
    assert "abatementDateTime" not in cond, (
        "Outpatient without discharge_dt should NOT have abatementDateTime"
    )


def test_jp_locale_chronic_primary_no_abatement():
    """JP locale: chronic primary should also comply with con-4 invariant."""
    record = _make_ctx(
        discharge_dt="2026-01-05T15:00:00Z",
        is_chronic_primary=True,
        country="JP",
    )
    conditions = _build_conditions(record, patient_id="pt-123", country="JP")

    assert len(conditions) == 1
    cond = conditions[0]

    clinical_status = cond["clinicalStatus"]["coding"][0]["code"]
    assert clinical_status == "active"
    assert "abatementDateTime" not in cond, (
        "JP locale: chronic primary should also NOT have abatementDateTime"
    )


def test_deceased_patient_acute_primary_no_abatement():
    """Deceased patient with acute primary: clinicalStatus='active' (didn't resolve), no abatement.

    When a patient dies during an acute encounter, the clinicalStatus remains
    'active' (the diagnosis didn't resolve due to death). No abatement is
    emitted in this case either.
    """
    record = _make_ctx(
        discharge_dt="2026-01-05T15:00:00Z",
        is_chronic_primary=False,
    )
    record["deceased"] = True
    conditions = _build_conditions(record, patient_id="pt-123", country="US")

    assert len(conditions) == 1
    cond = conditions[0]

    # Deceased: diagnosis is still 'active' (unresolved) and no abatement
    clinical_status = cond["clinicalStatus"]["coding"][0]["code"]
    assert clinical_status == "active", (
        "Deceased patient's acute diagnosis should remain active"
    )
    assert "abatementDateTime" not in cond, (
        "Deceased patient should NOT have abatementDateTime (diagnosis didn't resolve)"
    )
