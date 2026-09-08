"""Encounter.reasonCode alignment via visit-purpose Z-codes (Issue #1186 F2, #1189 F4).

Before the fix, preventive / screening / vaccination / pediatric
visits whose encounter YAML lacked an explicit `icd10_code` fell
through to the generic `Z09` ("治療後フォローアップ" / "Follow-up
examination after treatment"). This produced an
`Encounter.reasonCode.text` of `治療後フォローアップ` on a pediatric
annual check whose SOAP subjective correctly said `年次健診`, i.e. the
structured code and the narrative disagreed.

`outpatient.py` now maps each named visit purpose to its Z-family
code so the FHIR emit path (which resolves reasonCode.text via
`code_lookup(...)`) produces text that matches the visit's purpose.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.patient import PatientProfile


def _dummy_patient() -> PatientProfile:
    p = PatientProfile(patient_id="pt-z-test")
    p.age = 8
    p.sex = "M"
    p.chronic_conditions = []
    p.current_medications = []
    return p


def _dummy_roster():
    from clinosim.modules.staff.engine import StaffRoster

    return StaffRoster()


def test_annual_health_screening_preserves_yaml_z00_00() -> None:
    # `annual_health_screening.yaml` already provides `icd10_code: Z00.00`.
    # JP FHIR emit maps Z00.00 → Z00.0 (`一般的医学的検査`) at reasonCode
    # emission time via `map_diagnosis_code`, so the outpatient CIF keeps
    # the US-CM code. PR E does NOT overwrite this — it only rescues
    # visits whose YAML has no code and would otherwise fall through to
    # Z09. Test locks in the "YAML wins" priority.
    rec = _simulate_outpatient_visit(
        _dummy_patient(),
        "health_screening",
        datetime(2026, 8, 1, 10, 0),
        _dummy_roster(),
        np.random.default_rng(0),
        chronic_code="annual_health_screening",
        followup_spec={"visit_reason": {"en": "Annual health screening", "ja": "年次健診"}},
        country="JP",
        department_id="primary_care",
    )
    assert rec.clinical_diagnosis.admission_diagnosis_code == "Z00.00"


def test_mammography_screening_preserves_yaml_z12_31() -> None:
    rec = _simulate_outpatient_visit(
        _dummy_patient(),
        "health_screening",
        datetime(2026, 8, 1, 10, 0),
        _dummy_roster(),
        np.random.default_rng(0),
        chronic_code="mammography_screening",
        country="JP",
        department_id="primary_care",
    )
    assert rec.clinical_diagnosis.admission_diagnosis_code == "Z12.31"


def test_colonoscopy_screening_preserves_yaml_z12_11() -> None:
    rec = _simulate_outpatient_visit(
        _dummy_patient(),
        "health_screening",
        datetime(2026, 8, 1, 10, 0),
        _dummy_roster(),
        np.random.default_rng(0),
        chronic_code="colonoscopy_screening",
        country="JP",
        department_id="primary_care",
    )
    assert rec.clinical_diagnosis.admission_diagnosis_code == "Z12.11"


def test_pediatric_well_child_visit_gets_z00() -> None:
    rec = _simulate_outpatient_visit(
        _dummy_patient(),
        "pediatric_visit",
        datetime(2026, 8, 1, 10, 0),
        _dummy_roster(),
        np.random.default_rng(0),
        chronic_code="well_child_school_age",
        country="JP",
        department_id="primary_care",
    )
    # Well-child (Z00) — not Z09 follow-up-after-treatment
    assert rec.clinical_diagnosis.admission_diagnosis_code == "Z00"


def test_pediatric_vaccination_visit_gets_z23() -> None:
    rec = _simulate_outpatient_visit(
        _dummy_patient(),
        "pediatric_visit",
        datetime(2026, 8, 1, 10, 0),
        _dummy_roster(),
        np.random.default_rng(0),
        chronic_code="vaccination_school_age",
        country="JP",
        department_id="primary_care",
    )
    assert rec.clinical_diagnosis.admission_diagnosis_code == "Z23"


def test_post_discharge_still_uses_z09() -> None:
    # PR E only relocates the fallback for preventive/screening/pediatric
    # visits; post-discharge follow-up correctly stays at Z09.
    rec = _simulate_outpatient_visit(
        _dummy_patient(),
        "post_discharge",
        datetime(2026, 8, 1, 10, 0),
        _dummy_roster(),
        np.random.default_rng(0),
        post_discharge_disease="bacterial_pneumonia",
        country="JP",
        department_id="primary_care",
    )
    assert rec.clinical_diagnosis.admission_diagnosis_code == "Z09"
