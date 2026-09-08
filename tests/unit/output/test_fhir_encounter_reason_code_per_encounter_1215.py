"""Issue #1215: Encounter.reasonCode is per-encounter, not record-level.

The `_bb_encounters` FHIR builder receives a `BundleContext` that carries
one record-level `admit_dx_code` (from `clinical_diagnosis
.admission_diagnosis_code`) and passes it to every encounter emitted for
that record. Before this fix, a companion vaccination encounter appended
by the immunization enricher (PR #1214, `ENC-VAX-…`) inherited the
record's primary IMP admission dx — e.g. a hospitalized burn patient's
flu-shot follow-up got `reasonCode.coding = T30.0` instead of Z23.

The fix threads a per-encounter admission dx through the CIF
`Encounter` dataclass (`admission_diagnosis_code`) that the FHIR builder
prefers over the record-level fallback. The companion-vax enricher
stamps Z23 (`Encounter for immunization`), a visit-reason Z-code that
`is_visit_reason_zcode` already recognises — no dangling Condition
reference is emitted (Issue #916 gate).

This test pins the per-encounter fan-out by feeding a two-encounter
record (T30.0 primary IMP + Z23 companion vax) through `_bb_encounters`
and asserting each Encounter carries its own reasonCode.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from clinosim.modules.output.fhir_r4.lib.common import BundleContext
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_encounters

pytestmark = pytest.mark.unit


def _mk_ctx(record: dict[str, Any], country: str) -> BundleContext:
    return BundleContext(
        record=record,
        country=country,
        roster_map={},
        hospital_config={},
        patient_data=record.get("patient", {}),
        patient_id=record["patient"]["patient_id"],
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code=record.get("clinical_diagnosis", {}).get("discharge_diagnosis_code", ""),
        admit_dx_code=record.get("clinical_diagnosis", {}).get("admission_diagnosis_code", ""),
        admit_dx_system="icd-10-cm",
        primary_enc_id=record["encounters"][0]["encounter_id"] if record.get("encounters") else "",
        patient_sex=record["patient"].get("sex", ""),
    )


def _build_two_encounter_record() -> dict[str, Any]:
    # Primary IMP (burn) — record-level admission dx = T30.0.
    imp = {
        "encounter_id": "ENC-POP-000001-abc",
        "patient_id": "POP-000001",
        "encounter_type": "inpatient",
        "status": "finished",
        "admission_datetime": datetime(2026, 3, 1, 8, 0),
        "discharge_datetime": datetime(2026, 3, 10, 12, 0),
        "chief_complaint": "Burn injury",
        "chief_complaint_ja": "熱傷",
    }
    # Companion vaccination encounter — stamps Z23 as its own admission dx.
    vax = {
        "encounter_id": "ENC-VAX-POP-000001-deadbeef1234",
        "patient_id": "POP-000001",
        "encounter_type": "outpatient",
        "status": "finished",
        "admission_datetime": datetime(2026, 10, 1, 10, 0),
        "discharge_datetime": datetime(2026, 10, 1, 10, 0),
        "chief_complaint": "Vaccination visit",
        "chief_complaint_ja": "予防接種",
        "admission_diagnosis_code": "Z23",
        "admission_diagnosis_system": "icd-10-cm",
    }
    return {
        "patient": {
            "patient_id": "POP-000001",
            "sex": "F",
            "date_of_birth": date(1970, 5, 1),
            "chronic_conditions": [],
        },
        "encounters": [imp, vax],
        "clinical_diagnosis": {
            "admission_diagnosis_code": "T30.0",
            "discharge_diagnosis_code": "T30.0",
        },
        "is_readmission": False,
    }


def _cif_id(res: dict[str, Any]) -> str:
    """Return the CIF encounter_id stored on identifier[0].value."""
    for ident in res.get("identifier", []) or []:
        val = ident.get("value", "")
        if val:
            return val
    return ""


def _codes_in_reason(res: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for rc in res.get("reasonCode", []) or []:
        for coding in rc.get("coding", []) or []:
            code = coding.get("code", "")
            if code:
                out.append(code)
    return out


def test_companion_vax_encounter_carries_z23_reasoncode() -> None:
    """The Z23-stamped companion encounter emits Z23 (not the record's T30.0)."""
    ctx = _mk_ctx(_build_two_encounter_record(), "US")
    resources = _bb_encounters(ctx)
    # Find the VAX encounter resource by its CIF encounter_id (stored as identifier).
    vax_res = next(r for r in resources if _cif_id(r) == "ENC-VAX-POP-000001-deadbeef1234")
    codes = _codes_in_reason(vax_res)
    assert "Z23" in codes, f"expected Z23 in VAX encounter reasonCode, got {codes}"
    assert "T30.0" not in codes, f"VAX encounter must not inherit record-level T30.0, got {codes}"


def test_primary_imp_encounter_still_carries_record_admit_dx() -> None:
    """The primary IMP encounter (no per-encounter override) still uses the record-level admission dx."""
    ctx = _mk_ctx(_build_two_encounter_record(), "US")
    resources = _bb_encounters(ctx)
    imp_res = next(r for r in resources if _cif_id(r) == "ENC-POP-000001-abc")
    codes = _codes_in_reason(imp_res)
    assert "T30.0" in codes, f"IMP encounter should carry T30.0 from record-level admit_dx, got {codes}"


def test_companion_vax_has_no_dangling_condition_ref() -> None:
    """Z23 is a visit-reason zcode — no Condition emitted, so no reasonReference dangles."""
    ctx = _mk_ctx(_build_two_encounter_record(), "US")
    resources = _bb_encounters(ctx)
    vax_res = next(r for r in resources if _cif_id(r) == "ENC-VAX-POP-000001-deadbeef1234")
    # `reasonReference` is skipped for visit-reason zcodes (Issue #916).
    assert "reasonReference" not in vax_res, (
        f"VAX encounter must not emit reasonReference for Z23 visit-reason code, got {vax_res.get('reasonReference')}"
    )


def test_jp_vax_encounter_z23_and_ja_chief_complaint() -> None:
    """JP output: Z23 reasonCode with Japanese fallback text where applicable."""
    ctx = _mk_ctx(_build_two_encounter_record(), "JP")
    resources = _bb_encounters(ctx)
    vax_res = next(r for r in resources if _cif_id(r) == "ENC-VAX-POP-000001-deadbeef1234")
    codes = _codes_in_reason(vax_res)
    assert "Z23" in codes
    # text should not be a burn-related string (T30.0 leakage guard).
    rc_text = (vax_res.get("reasonCode") or [{}])[0].get("text", "")
    assert "熱傷" not in rc_text and "Burn" not in rc_text
