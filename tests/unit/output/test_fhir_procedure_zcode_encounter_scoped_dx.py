"""Procedure.reasonReference Z-code gate uses per-encounter dx (Issue #1222 residual fix).

PR #1223 landed the Z-code gate on Procedure.reasonReference emit but
looked at record-level ``clinical_diagnosis`` only. Issue #1215
introduced per-encounter ``Encounter.admission_diagnosis_code`` so a
companion vaccination encounter (``ENC-VAX-*``, appended by the
immunization enricher for orphan doses — Issue #1197 Pass 5 fix)
carries its own visit-reason Z23. When the record's primary IMP dx is
non-Z-code (e.g. T30.0 burn) but the current encounter is the VAX
companion (Z23), the gate did not fire and the Procedure emitted a
dangling reasonReference to a Condition never emitted.

S105 v2 audit (JP p=10k) found 41 residual Procedure→Condition
dangling refs after PR #1223 — all VAX-companion cross-layer cases.
This test pins the encounter-scoped dx lookup that closes them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from clinosim.modules.diagnosis.nonspecific_codes import encounter_primary_dx_code
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

pytestmark = pytest.mark.unit


def _mk_record(record_admit_dx: str, vax_enc_dx: str = "Z23") -> dict[str, Any]:
    """Two-encounter record: primary IMP with `record_admit_dx` + VAX companion with `vax_enc_dx`."""
    return {
        "patient": {"patient_id": "POP-000001", "sex": "F"},
        "encounters": [
            {
                "encounter_id": "ENC-POP-000001-imp",
                "encounter_type": "inpatient",
                "status": "finished",
                "admission_datetime": datetime(2026, 3, 1, 8, 0),
                "discharge_datetime": datetime(2026, 3, 10, 12, 0),
            },
            {
                "encounter_id": "ENC-VAX-POP-000001-abcd1234",
                "encounter_type": "outpatient",
                "status": "finished",
                "admission_datetime": datetime(2026, 10, 1, 10, 0),
                "discharge_datetime": datetime(2026, 10, 1, 10, 0),
                "admission_diagnosis_code": vax_enc_dx,
                "admission_diagnosis_system": "icd-10-cm",
            },
        ],
        "clinical_diagnosis": {
            "admission_diagnosis_code": record_admit_dx,
            "discharge_diagnosis_code": record_admit_dx,
        },
    }


def _mk_procedure(enc_id: str) -> dict[str, Any]:
    return {
        "procedure_id": "PROC-1",
        "encounter_id": enc_id,
        "code": "999.99",
        "display": "Some procedure",
        "started_at": datetime(2026, 10, 1, 10, 5),
        "ended_at": datetime(2026, 10, 1, 10, 10),
        "status": "completed",
    }


def test_encounter_primary_dx_code_prefers_encounter_scoped() -> None:
    record = _mk_record("T30.0", vax_enc_dx="Z23")
    assert encounter_primary_dx_code(record, "ENC-VAX-POP-000001-abcd1234") == "Z23"
    assert encounter_primary_dx_code(record, "ENC-POP-000001-imp") == "T30.0"


def test_encounter_primary_dx_code_empty_encounter_falls_back_to_record() -> None:
    """Encounter without admission_diagnosis_code falls back to record.clinical_diagnosis."""
    record = _mk_record("T30.0", vax_enc_dx="")
    assert encounter_primary_dx_code(record, "ENC-VAX-POP-000001-abcd1234") == "T30.0"


def test_encounter_primary_dx_code_none_record() -> None:
    assert encounter_primary_dx_code(None, "ENC-any") == ""


def test_encounter_primary_dx_code_missing_encounter_id() -> None:
    record = _mk_record("T30.0")
    assert encounter_primary_dx_code(record, "ENC-nope") == "T30.0"  # falls back


def test_procedure_omits_reason_ref_for_vax_companion_encounter() -> None:
    """Core fix: VAX companion encounter's Procedure gates on Z23, omits reasonReference."""
    record = _mk_record("T30.0", vax_enc_dx="Z23")
    proc = _build_procedure(_mk_procedure("ENC-VAX-POP-000001-abcd1234"), "POP-000001", 0, "US", record=record)
    assert "reasonReference" not in proc, (
        f"VAX companion Procedure must gate on encounter-scoped Z23, got {proc.get('reasonReference')}"
    )


def test_procedure_emits_reason_ref_for_imp_encounter_in_same_record() -> None:
    """Regression guard: sibling IMP encounter (non-Z-code) still emits reasonReference."""
    record = _mk_record("T30.0", vax_enc_dx="Z23")
    proc = _build_procedure(_mk_procedure("ENC-POP-000001-imp"), "POP-000001", 0, "US", record=record)
    assert "reasonReference" in proc, "IMP encounter should still carry reasonReference"


def test_procedure_omits_reason_ref_when_encounter_z23_but_record_also_zcode() -> None:
    """Both encounter and record Z-code: still omitted (defensive)."""
    record = _mk_record("Z00.0", vax_enc_dx="Z23")
    proc = _build_procedure(_mk_procedure("ENC-VAX-POP-000001-abcd1234"), "POP-000001", 0, "US", record=record)
    assert "reasonReference" not in proc
