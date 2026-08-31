"""Issue #957 male-C50 activation — end-to-end FHIR Condition emit path.

Guards the full plumbing that lets a male patient carry a C50 (breast
cancer) chronic condition and receive the anatomy-appropriate ICD-10-CM
leaf on the emitted ``Condition.code``:

* Pre-fix, C50 was hard-locked female-only via
  ``icd10_sex_restrictions.yaml``; the sex-gate would have blocked any
  male dispatch. The lock is lifted for C50 (only; C51-C58 sibling
  female-genital codes stay locked).
* ``chronic_prevalence`` for C50 uses the ``by_sex`` schema so male BC
  emits at ~1 % of the C50 total (SEER 2020 male BC ~1.3 per 100k).
* US ICD-10-CM splits C50 into female (``C50.919``) / male (``C50.929``)
  unspecified-site leaves. ``map_diagnosis_code(..., sex=…)`` routes the
  chronic Condition to the sex-appropriate billable code so a male BC
  patient no longer receives a "female breast" code.
* JP ICD-10 has no per-sex C50 subcategory — the JP mapping stays
  identity for both sexes.

Unit-level guards (parser, mapper, sex-gate) live in the sibling test
files (``test_sex_gating.py``, ``test_diagnosis_code_mapping.py``,
``test_population_demographics.py``). This file exercises the actual
FHIR builder to prove the plumbing lines up end-to-end.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions

pytestmark = pytest.mark.unit


def _make_c50_chronic_record(sex: str) -> dict:
    """Minimal record: one chronic C50, one outpatient follow-up encounter,
    patient sex per parameter. Mirrors ``_make_zcode_record`` in the
    sibling Issue #916 test file."""
    return {
        "patient": {
            "patient_id": "POP-000001",
            "sex": sex,
            "age": 70,
            "chronic_conditions": [
                {"code": "C50", "onset_date": "2020-03-15", "severity": "", "stage": ""},
            ],
        },
        "encounters": [
            {
                "encounter_id": "enc-c50-957",
                "encounter_type": "outpatient",
                "admission_datetime": "2026-04-12T10:00:00+09:00",
                "discharge_datetime": "2026-04-12T10:30:00+09:00",
                "status": "completed",
                "attending_physician_id": "STAFF-P-001",
                "chief_complaint": "Breast cancer follow-up",
            }
        ],
        "clinical_diagnosis": {
            "admission_diagnosis_code": "C50",
            "admission_diagnosis_system": "icd-10-cm",
            "discharge_diagnosis_code": "C50",
            "discharge_diagnosis_system": "icd-10-cm",
        },
        "deceased": False,
    }


def _c50_coding_codes(conditions: list[dict]) -> list[str]:
    """Extract every C50* code from every Condition.code.coding."""
    out: list[str] = []
    for cond in conditions:
        for coding in cond.get("code", {}).get("coding") or []:
            code = coding.get("code", "")
            if code.startswith("C50"):
                out.append(code)
    return out


def test_male_c50_emits_c50_929_on_us_condition() -> None:
    """Regression: US ``_build_conditions`` for a male patient with C50
    on the chronic list must emit ``C50.929`` (male-side unspecified
    breast) — NOT ``C50.919`` (female-side) which would be an
    anatomically-incorrect billing code."""
    record = _make_c50_chronic_record(sex="M")
    conditions = _build_conditions(record, patient_id="POP-000001", country="US")
    c50_codes = _c50_coding_codes(conditions)
    assert c50_codes, "Male C50 patient must still emit a C50 Condition (sex-gate must NOT block C50)"
    assert "C50.929" in c50_codes, f"Male C50 must map to C50.929, got {c50_codes!r}"
    assert "C50.919" not in c50_codes, f"Male C50 must NOT emit female-anatomy C50.919; got {c50_codes!r}"


def test_female_c50_still_emits_c50_919_on_us_condition() -> None:
    """Baseline: female C50 continues to map to C50.919 (the pre-#957
    behaviour for the ~99 %-of-cases pick)."""
    record = _make_c50_chronic_record(sex="F")
    conditions = _build_conditions(record, patient_id="POP-000001", country="US")
    c50_codes = _c50_coding_codes(conditions)
    assert c50_codes, "Female C50 patient must emit a C50 Condition"
    assert "C50.919" in c50_codes, f"Female C50 must map to C50.919, got {c50_codes!r}"
    assert "C50.929" not in c50_codes, f"Female C50 must NOT emit male-anatomy C50.929, got {c50_codes!r}"


def test_male_c50_jp_emit_uses_identity_mapping() -> None:
    """JP ICD-10 has no per-sex C50 subcategory; both sexes must emit
    the identity ``C50`` code (no drift, no fallback to some CM
    granular leaf under the WHO system URI)."""
    for sex in ("F", "M"):
        record = _make_c50_chronic_record(sex=sex)
        conditions = _build_conditions(record, patient_id="POP-000001", country="JP")
        c50_codes = _c50_coding_codes(conditions)
        assert c50_codes, f"JP C50 patient (sex={sex}) must emit a C50 Condition"
        assert "C50" in c50_codes, f"JP C50 (sex={sex}) must emit identity C50, got {c50_codes!r}"
        assert not any(c.startswith("C50.") for c in c50_codes), (
            f"JP must NOT emit CM-granular C50.* leaves (sex={sex}), got {c50_codes!r}"
        )
