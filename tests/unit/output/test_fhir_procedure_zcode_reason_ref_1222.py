"""Issue #1222: Procedure.reasonReference gate for Z-chapter visit-reason codes.

The three Procedure emit sites (`procedures.py`, `oxygen_therapy.py`,
`lib/inline_bb.py::_bb_procedures`) unconditionally attached a
`reasonReference` pointing at the encounter's primary Condition. When
the primary dx is a Z-chapter visit-reason code (Z00.0 general medical,
Z09 follow-up, Z12/Z13 screening, Z23 immunization, …) `conditions.py`
does not emit a Condition (Issue #916 gate). The dangling
`Procedure/… -> Condition/…` reference broke reference-integrity on
FHIR consumers.

Fix: mirror the `is_visit_reason_zcode` gate from `encounter.py` at all
three Procedure emit sites. When the primary dx is a visit-reason
Z-code, skip `reasonReference` — `reasonCode.text/coding` (populated
downstream from the encounter's dx) alone carries the semantic.

P=10k audit finding: 45 dangling Procedure→Condition refs eliminated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

pytestmark = pytest.mark.unit


def _mk_record(admission_dx_code: str, discharge_dx_code: str = "") -> dict[str, Any]:
    return {
        "patient": {"patient_id": "POP-000001", "sex": "F"},
        "encounters": [
            {
                "encounter_id": "ENC-POP-000001-abc",
                "encounter_type": "outpatient",
                "status": "finished",
                "admission_datetime": datetime(2026, 3, 1, 10, 0),
                "discharge_datetime": datetime(2026, 3, 1, 10, 30),
            }
        ],
        "clinical_diagnosis": {
            "admission_diagnosis_code": admission_dx_code,
            "discharge_diagnosis_code": discharge_dx_code or admission_dx_code,
        },
    }


def _mk_procedure() -> dict[str, Any]:
    return {
        "procedure_id": "PROC-1",
        "encounter_id": "ENC-POP-000001-abc",
        "code": "999.99",
        "display": "General checkup",
        "started_at": datetime(2026, 3, 1, 10, 5),
        "ended_at": datetime(2026, 3, 1, 10, 10),
        "status": "completed",
    }


def test_procedure_omits_reason_ref_when_primary_dx_is_zcode() -> None:
    """Primary dx = Z00.0 → no reasonReference (Condition not emitted)."""
    record = _mk_record("Z00.0")
    proc = _build_procedure(_mk_procedure(), "POP-000001", 0, "US", record=record)
    assert "reasonReference" not in proc, (
        f"Procedure must not emit reasonReference for Z-code visit-reason primary dx, got {proc.get('reasonReference')}"
    )


def test_procedure_omits_reason_ref_when_primary_dx_is_z23() -> None:
    """Primary dx = Z23 (immunization) → no reasonReference."""
    record = _mk_record("Z23")
    proc = _build_procedure(_mk_procedure(), "POP-000001", 0, "US", record=record)
    assert "reasonReference" not in proc


def test_procedure_emits_reason_ref_for_real_condition() -> None:
    """Primary dx = J44 (COPD) → reasonReference populated (Condition is emitted)."""
    record = _mk_record("J44.9")
    proc = _build_procedure(_mk_procedure(), "POP-000001", 0, "US", record=record)
    assert "reasonReference" in proc
    refs = proc["reasonReference"]
    assert refs and refs[0]["reference"].startswith("Condition/")


def test_procedure_emits_reason_ref_for_e11_dm() -> None:
    """Primary dx = E11 (diabetes chronic) → reasonReference populated."""
    record = _mk_record("E11.9")
    proc = _build_procedure(_mk_procedure(), "POP-000001", 0, "JP", record=record)
    assert "reasonReference" in proc


def test_procedure_still_emits_reason_code_for_zcode() -> None:
    """reasonCode should still be populated for Z-code encounters (text/coding
    carries the semantic even without the Condition reference)."""
    record = _mk_record("Z00.0")
    proc = _build_procedure(_mk_procedure(), "POP-000001", 0, "US", record=record)
    assert "reasonCode" in proc
    assert proc["reasonCode"], "reasonCode must be populated even without reasonReference"


def test_procedure_omits_reason_ref_when_z09_follow_up() -> None:
    """Primary dx = Z09 (follow-up) → no reasonReference."""
    record = _mk_record("Z09")
    proc = _build_procedure(_mk_procedure(), "POP-000001", 0, "US", record=record)
    assert "reasonReference" not in proc
