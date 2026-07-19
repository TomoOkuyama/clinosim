"""Regression test for MedicationAdministration.reasonCode ICD-10 mapping.

fhir-jp-validator 2026-07-17 report (§【最優先 6】) surfaced 7,652 errors
on JP Condition-adjacent resources emitting ICD-10-CM-granular codes
(``S72.00`` = 4,052, ``E11.65`` = 3,600) on the WHO ICD-10 system URI
``http://hl7.org/fhir/sid/icd-10``. WHO ICD-10 tops out at 3-4 char
codes (``S72.0`` / ``E11.6``); the 5-char forms are ICD-10-CM leaves.
JP should emit the WHO parent.

The remaining leak site was ``MedicationAdministration.reasonCode`` in
``_fhir_medications._build_medication_admin`` which emitted the raw
``primary_dx_code`` (CIF ``admission_diagnosis_code``, which carries
the disease-YAML ``icd_codes.primary`` value verbatim, i.e.
``S72.00`` for hip fracture / ``E11.65`` for DKA). Every other builder
that emits a diagnosis code (Encounter.reasonCode, Condition.code,
FamilyMemberHistory.code) already routed through
``_map_diagnosis_code``. This test pins the fix at the MAR seam.

Issue: #208.
"""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.codes import get_system_uri
from clinosim.modules.output._fhir_medications import _build_medication_admin

pytestmark = pytest.mark.unit


def _build_mar(country: str, primary_dx_code: str) -> dict[str, Any]:
    mar = {
        "mar_id": "MAR-1",
        "drug_name": "Test drug",
        "administration_datetime": "2026-06-01T10:00:00",
        "dose": "500 mg",
        "route": "oral",
        "status": "given",
    }
    return _build_medication_admin(
        mar,
        patient_id="pt1",
        index=1,
        country=country,
        encounter_id="enc1",
        primary_dx_code=primary_dx_code,
    )


def test_mar_reason_code_maps_hip_fracture_cm_to_who_on_jp() -> None:
    """S72.00 (CM-granular) → S72.0 (WHO ICD-10) on JP output."""
    resource = _build_mar(country="JP", primary_dx_code="S72.00")
    reason = resource["reasonCode"][0]
    assert reason["coding"][0]["system"] == get_system_uri("icd-10")
    assert reason["coding"][0]["code"] == "S72.0"


def test_mar_reason_code_maps_dka_cm_to_who_on_jp() -> None:
    """E11.65 (CM-granular) → E11.6 (WHO ICD-10) on JP output."""
    resource = _build_mar(country="JP", primary_dx_code="E11.65")
    reason = resource["reasonCode"][0]
    assert reason["coding"][0]["system"] == get_system_uri("icd-10")
    assert reason["coding"][0]["code"] == "E11.6"


def test_mar_reason_code_passthrough_when_already_who_on_jp() -> None:
    """Codes already in WHO ICD-10 shape pass through unchanged."""
    resource = _build_mar(country="JP", primary_dx_code="I10")
    reason = resource["reasonCode"][0]
    assert reason["coding"][0]["code"] == "I10"


def test_mar_reason_code_us_maps_to_billable_cm_leaf() -> None:
    """US output maps the internal code to the billable ICD-10-CM leaf.

    ``code_mapping_diagnosis/us.yaml`` maps ``S72.00 → S72.009A`` (initial
    encounter for closed fracture). System URI is icd-10-cm on US output."""
    resource = _build_mar(country="US", primary_dx_code="S72.00")
    reason = resource["reasonCode"][0]
    assert reason["coding"][0]["system"] == get_system_uri("icd-10-cm")
    assert reason["coding"][0]["code"] == "S72.009A"


def test_mar_reason_code_omitted_when_no_dx_code() -> None:
    """When no primary diagnosis is provided, no reasonCode is emitted."""
    resource = _build_mar(country="JP", primary_dx_code="")
    assert "reasonCode" not in resource


def test_mar_nocoded_display_pinned_to_authoritative_value() -> None:
    """#305 session 60:MedicationAdministration.medicationCodeableConcept
    に nocoded fallback を emit するとき、display は権威 CodeSystem 定義
    通り "標準コードなし" 固定。薬剤名は CodeableConcept.text で保持。

    v6 validation で MAR に 12,565 件の display mismatch error が出た
    regression の pin(v6 total 15,148 errors の 83%)。session 59 の
    drug_name-in-display は権威 CodeSystem `MedicationCodeNocoded_CS`
    (NOCODED 1 code / "標準コードなし" 1 display の required binding)
    に反していた。
    """
    from clinosim.modules.output._fhir_medications import (
        _JP_MEDICATION_CODE_NOCODED_CODE,
        _JP_MEDICATION_CODE_NOCODED_CS,
        _JP_MEDICATION_CODE_NOCODED_DISPLAY,
    )

    # JP + unknown drug (code_mapping にヒットしない) → nocoded fallback
    mar = {
        "mar_id": "MAR-1",
        "drug_name": "some_unknown_med 5mg",
        "administration_datetime": "2026-06-01T10:00:00",
        "dose": "5 mg",
        "route": "oral",
        "status": "given",
    }
    resource = _build_medication_admin(
        mar,
        patient_id="pt1",
        index=1,
        country="JP",
        encounter_id="enc1",
        primary_dx_code="",
    )
    coding = resource["medicationCodeableConcept"]["coding"][0]
    assert coding["system"] == _JP_MEDICATION_CODE_NOCODED_CS
    assert coding["code"] == _JP_MEDICATION_CODE_NOCODED_CODE == "NOCODED"
    assert coding["display"] == _JP_MEDICATION_CODE_NOCODED_DISPLAY == "標準コードなし"
    # 薬剤名は text field で保持
    assert resource["medicationCodeableConcept"]["text"]
    assert (
        "some_unknown_med" in resource["medicationCodeableConcept"]["text"].lower()
        or (resource["medicationCodeableConcept"]["text"])
    )
