"""Issue #916: ICD-10 Z-chapter visit-reason codes are not Conditions.

The Z-chapter ("Factors influencing health status and contact with health
services") describes reasons for encountering the health system — routine
checkups, immunization visits, aftercare follow-up, screening exams — not
clinical diagnoses. Post-fix ``_build_conditions`` no longer emits a
``Condition`` when the primary / admission dx is a visit-reason Z-code
(Z00/Z01/Z02/Z09/Z11/Z12/Z13/Z23/Z25-29/Z71/Z76). ``Encounter.reasonCode``
still carries the code; ``diagnosis[]`` and ``reasonReference`` are
suppressed by the mirror guard in ``encounters/encounter.py`` so no
dangling refs remain.

Personal-history / device-presence Z-codes (``Z80``-``Z99``) are clinical
facts and MUST still emit as Conditions.
"""

from __future__ import annotations

import pytest

from clinosim.modules.diagnosis.nonspecific_codes import is_visit_reason_zcode
from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter

pytestmark = pytest.mark.unit


# === Helper predicate contract ===


@pytest.mark.parametrize(
    "code",
    [
        "Z09",
        "Z00.0",
        "Z00.1",
        "Z01",
        "Z02.9",
        "Z11.3",
        "Z12.1",
        "Z12.3",
        "Z13.5",
        "Z23",
        "Z25.1",
        "Z27",
        "Z28.1",
        "Z29.9",
        "Z71.4",
        "Z76.5",
    ],
)
def test_visit_reason_zcode_predicate_matches_visit_reason_codes(code: str) -> None:
    assert is_visit_reason_zcode(code), f"{code} should classify as visit-reason"


@pytest.mark.parametrize(
    "code",
    [
        # Clinical facts (personal history / device presence) — remain valid
        # Conditions.
        "Z80.0",
        "Z85.3",
        "Z90.5",
        "Z93.2",
        "Z95.1",
        "Z99.1",
        # Non-Z codes are trivially non-visit-reason.
        "I10",
        "E11.9",
        "J44.1",
        "N39.0",
        "",
        None,
    ],
)
def test_visit_reason_zcode_predicate_rejects_non_visit_reason_codes(code) -> None:
    assert not is_visit_reason_zcode(code or ""), f"{code!r} must NOT classify as visit-reason"


# === Emit-path contract ===


def _make_zcode_record(dx_code: str) -> dict:
    """Minimal record with only a primary dx set — no chronic list, no other
    Conditions to compete."""
    return {
        "patient": {"chronic_conditions": []},
        "encounters": [
            {
                "encounter_id": "enc-test-916",
                "encounter_type": "outpatient",
                "admission_datetime": "2026-04-12T10:00:00+09:00",
                "discharge_datetime": "2026-04-12T10:30:00+09:00",
                "status": "completed",
                "attending_physician_id": "STAFF-P-001",
                "chief_complaint": "Follow-up",
            }
        ],
        "clinical_diagnosis": {
            "admission_diagnosis_code": dx_code,
            "admission_diagnosis_system": "icd-10-cm",
            "discharge_diagnosis_code": dx_code,
            "discharge_diagnosis_system": "icd-10-cm",
        },
        "deceased": False,
    }


@pytest.mark.parametrize("dx_code", ["Z09", "Z00.0", "Z23", "Z12.1", "Z12.3", "Z13.5"])
def test_zcode_primary_dx_does_not_emit_condition(dx_code: str) -> None:
    """Regression: the 6 visit-reason Z-codes observed in the audit must not
    produce a ``Condition`` resource. (Audit v0.5.0 ``de261adf``: these
    accounted for 14,384 / 33,188 = 43.3 % of all Conditions, every one a
    same-day ``resolved`` pseudo-diagnosis.)"""
    record = _make_zcode_record(dx_code)
    conditions = _build_conditions(record, patient_id="POP-000001", country="US")
    assert conditions == [], (
        f"Z-code {dx_code} still emitted a Condition: "
        f"{[(c.get('id'), c.get('code', {}).get('text')) for c in conditions]!r}"
    )


def test_clinical_zcode_z95_still_emits_condition() -> None:
    """Z95.1 (presence of aortocoronary bypass graft) is a clinical fact,
    not a visit reason — must still emit as a Condition (regression guard
    for over-broad skip)."""
    record = _make_zcode_record("Z95.1")
    conditions = _build_conditions(record, patient_id="POP-000001", country="US")
    # At least one Condition emitted (the primary dx path fires).
    assert conditions, "Z95.1 (clinical fact) must still emit as Condition"


def test_non_zcode_primary_dx_still_emits_condition() -> None:
    """Baseline: a real diagnosis (N39.0 UTI) still emits normally."""
    record = _make_zcode_record("N39.0")
    conditions = _build_conditions(record, patient_id="POP-000001", country="US")
    assert conditions, "Non-Z primary dx must still emit as Condition"


def _make_encounter_dict(dx_code: str) -> dict:
    return {
        "encounter_id": "enc-test-916",
        "encounter_type": "outpatient",
        "admission_datetime": "2026-04-12T10:00:00+09:00",
        "discharge_datetime": "2026-04-12T10:30:00+09:00",
        "status": "completed",
        "attending_physician_id": "STAFF-P-001",
        "chief_complaint": "Follow-up",
    }


def test_encounter_zcode_primary_dx_reasoncode_populated_no_reasonreference() -> None:
    """Encounter still carries the Z-code on ``reasonCode`` (text + coding),
    but the mirror guard suppresses ``reasonReference`` so no dangling
    ``Condition/…`` reference is emitted."""
    enc = _build_encounter(
        _make_encounter_dict("Z09"),
        patient_id="POP-000001",
        country="US",
        primary_dx_code="Z09",
        chronic_condition_codes=[],
        admit_dx_code="Z09",
    )
    # reasonCode present and includes Z09 coding
    rcs = enc.get("reasonCode") or []
    assert rcs, "Encounter.reasonCode must remain populated for Z-code visits"
    coding = (rcs[0].get("coding") or [{}])[0].get("code", "")
    assert coding == "Z09", f"reasonCode.coding.code should be Z09, got {coding!r}"
    # reasonReference must NOT emit — no matching Condition exists
    assert "reasonReference" not in enc, "Encounter.reasonReference must be suppressed for Z-code primary dx"


def test_encounter_zcode_primary_dx_no_dangling_diagnosis_ref() -> None:
    """When the primary dx is a Z-code and no chronic Conditions exist,
    ``Encounter.diagnosis`` must not contain a reference to the (non-existent)
    primary Condition. A dangling ``Condition/`` reference must never appear."""
    enc = _build_encounter(
        _make_encounter_dict("Z09"),
        patient_id="POP-000001",
        country="US",
        primary_dx_code="Z09",
        chronic_condition_codes=[],
        admit_dx_code="Z09",
    )
    # No diagnosis[] entries when primary is a Z-code and no chronics
    diag = enc.get("diagnosis") or []
    assert diag == [] or all(
        "Condition/cond-enc-test-916-primary" not in (d.get("condition") or {}).get("reference", "") for d in diag
    ), f"dangling Condition ref for Z-code visit: {diag!r}"
