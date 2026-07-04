"""β-JP-1 chain 1a T2 (spec §2b): NarrativePass._build_context real-schema wiring.

Pins every ctx mapping against the real structural CIF JSON schema
(vital_signs / medication_administrations / clinical_diagnosis /
patient.allergies / encounter.severity / encounter.clinical_course_archetype /
condition_event-driven protocol resolution / per-stub day_index / los_days),
plus old-CIF (pre-1a JSON) backward compat.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from clinosim.modules.document import specs_for_country
from clinosim.modules.document.narrative.passes import TemplateNarrativePass
from clinosim.types.document import NarrativeOutput

pytestmark = pytest.mark.unit


def _spec(type_key: str, country: str = "us"):
    for s in specs_for_country(country):
        if s.type_key == type_key:
            return s
    raise AssertionError(f"spec {type_key} not found for {country}")


def _patient_dict(**overrides: Any) -> dict[str, Any]:
    """Minimal structural-CIF-shaped patient dict (real production keys)."""
    base: dict[str, Any] = {
        "patient": {
            "patient_id": "POP-000001",
            "age": 65,
            "sex": "M",
            "chronic_conditions": [],
            "current_medications": ["Amlodipine 5mg"],
            "allergies": [
                {"allergen_code": "387207008", "criticality": "high"},
            ],
        },
        "encounters": [
            {
                "encounter_id": "ENC-1",
                "encounter_type": "inpatient",
                "admission_datetime": "2025-06-01T10:00:00",
                "discharge_datetime": "2025-06-06T11:00:00",
                "severity": "severe",
                "clinical_course_archetype": "uncomplicated_improvement",
                "attending_physician_id": "DR-1",
            }
        ],
        "condition_event": {
            "condition_id": "COND-POP-000001-001",
            "condition_type": "known_disease",
            "ground_truth_diseases": ["bacterial_pneumonia"],
        },
        "clinical_diagnosis": {
            "admission_diagnosis_code": "J15.9",
            "admission_diagnosis_system": "icd-10-cm",
            "discharge_diagnosis_code": "J15.9",
            "discharge_diagnosis_system": "icd-10-cm",
        },
        "vital_signs": [
            {"timestamp": "2025-06-01T12:00:00", "heart_rate": 92},
        ],
        "lab_results": [
            {"lab_name": "CRP", "value": 8.2, "result_datetime": "2025-06-01T13:00:00"},
        ],
        "medication_administrations": [
            {"drug_name": "Ceftriaxone", "dose": "1g", "status": "given"},
        ],
        "discharge_prescription": {
            "prescription_id": "RX-1",
            "items": [{"drug": "Amoxicillin 500mg", "duration_days": 7}],
        },
        "procedures": [],
        "physiological_states": [{}, {}, {}, {}, {}, {}],  # admission + 5 days
        "documents": [],
    }
    base.update(overrides)
    return base


def _build_ctx(patient_dict: dict[str, Any], type_key: str = "admission_hp",
               country: str = "US", language: str = "en"):
    p = TemplateNarrativePass(cif_dir="/nonexistent", country=country)
    encounter_dict = (patient_dict.get("encounters") or [{}])[0]
    return p._build_context(
        patient_dict, encounter_dict, _spec(type_key, country.lower()), language
    )


# ─── field mappings ──────────────────────────────────────────────────────


def test_vitals_read_from_vital_signs_key():
    ctx = _build_ctx(_patient_dict())
    assert len(ctx.vitals) == 1
    assert ctx.vitals[0]["heart_rate"] == 92


def test_medications_are_mar_only_and_rx_goes_to_discharge_medications():
    """adv-1 I-1: sources separated — MAR never leaks into discharge meds."""
    ctx = _build_ctx(_patient_dict())
    assert [m.get("drug_name", "") for m in ctx.medications] == ["Ceftriaxone"]
    # discharge_prescription items are normalized to the consumer shape
    # (drug_name key) on the dedicated field — see spec §2b + adv-1 I-1.
    assert [m["drug_name"] for m in ctx.discharge_medications] == ["Amoxicillin 500mg"]


def test_medications_without_discharge_prescription():
    ctx = _build_ctx(_patient_dict(discharge_prescription=None))
    assert [m["drug_name"] for m in ctx.medications] == ["Ceftriaxone"]
    assert ctx.discharge_medications == []


def test_diagnoses_wrap_clinical_diagnosis_dict():
    ctx = _build_ctx(_patient_dict())
    assert len(ctx.diagnoses) == 1
    assert ctx.diagnoses[0]["discharge_diagnosis_code"] == "J15.9"


def test_allergies_read_from_patient_allergies():
    """Context building passes allergies through unresolved — display
    resolution happens later, in TemplateNarrativeGenerator._build_allergies
    via code_lookup (AD-30)."""
    ctx = _build_ctx(_patient_dict())
    assert len(ctx.allergies) == 1
    assert ctx.allergies[0]["allergen_code"] == "387207008"


def test_severity_and_archetype_read_from_encounter():
    ctx = _build_ctx(_patient_dict())
    assert ctx.severity == "severe"
    assert ctx.clinical_course_archetype == "uncomplicated_improvement"


def test_encounter_type_populated_from_encounter_dict():
    ctx = _build_ctx(_patient_dict())
    assert ctx.encounter_type == "inpatient"


# ─── protocol resolution ─────────────────────────────────────────────────


def test_disease_protocol_resolved_for_known_disease():
    ctx = _build_ctx(_patient_dict())
    assert ctx.disease_protocol is not None
    assert ctx.disease_protocol.disease_id == "bacterial_pneumonia"


def test_disease_protocol_none_for_unknown_disease_id(caplog):
    pd = _patient_dict()
    pd["condition_event"]["ground_truth_diseases"] = ["no_such_disease_xyz"]
    with caplog.at_level("WARNING"):
        ctx = _build_ctx(pd)
    assert ctx.disease_protocol is None
    assert any("no_such_disease_xyz" in r.message for r in caplog.records)


def test_disease_protocol_none_for_non_known_disease_condition_type():
    pd = _patient_dict()
    pd["condition_event"] = {
        "condition_type": "chronic_followup",
        "ground_truth_diseases": ["I10"],  # ICD code, NOT a disease id
    }
    ctx = _build_ctx(pd)
    assert ctx.disease_protocol is None


def test_encounter_protocol_resolved_for_ed_visit():
    pd = _patient_dict()
    pd["condition_event"] = {
        "condition_type": "ed_visit",
        "ground_truth_diseases": ["viral_gastroenteritis"],
    }
    pd["encounters"][0]["encounter_type"] = "emergency"
    ctx = _build_ctx(pd, type_key="ed_note")
    assert ctx.encounter_protocol is not None
    assert ctx.encounter_protocol.get("condition_id") == "viral_gastroenteritis"


def test_encounter_protocol_none_for_unloadable_condition(caplog):
    pd = _patient_dict()
    pd["condition_event"] = {
        "condition_type": "ed_visit",
        "ground_truth_diseases": ["no_such_condition_xyz"],
    }
    pd["encounters"][0]["encounter_type"] = "emergency"
    with caplog.at_level("WARNING"):
        ctx = _build_ctx(pd, type_key="ed_note")
    assert ctx.encounter_protocol is None


def test_narrative_spine_built_from_disease_protocol_and_archetype():
    ctx = _build_ctx(_patient_dict())
    assert ctx.narrative_spine is not None
    assert ctx.narrative_spine.archetype == "uncomplicated_improvement"


# ─── los_days + per-stub day_index ───────────────────────────────────────


def test_los_days_from_admission_to_discharge():
    ctx = _build_ctx(_patient_dict())
    assert ctx.los_days == 5


def test_los_days_in_progress_uses_physiological_states_proxy():
    pd = _patient_dict()
    pd["encounters"][0]["discharge_datetime"] = None
    pd["physiological_states"] = [{}, {}, {}, {}]  # admission + 3 days
    ctx = _build_ctx(pd)
    assert ctx.los_days == 3


def test_per_stub_day_index_and_los_via_run(tmp_path: Path):
    """Progress-note stubs on a multi-day stay get incrementing day_index."""
    pd = _patient_dict()
    pd["documents"] = [
        {
            "document_id": f"doc-ENC-1-progress_note-day-{d}",
            "task_type": "progress_note",
            "loinc_code": "11506-3",
            "format_type": "free_text",
            "period_start": f"2025-06-0{d + 1}T00:00:00",
            "authored_datetime": f"2025-06-0{d + 1}T00:00:00",
            "narrative": None,
        }
        for d in range(3)
    ]
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(json.dumps(pd, ensure_ascii=False))

    captured: list[tuple[int, int]] = []

    class CapturingGenerator:
        def generate(self, ctx, spec):
            captured.append((ctx.day_index, ctx.los_days))
            return NarrativeOutput(raw_text="x")

    TemplateNarrativePass(
        cif_dir=str(tmp_path), country="US", tasks=["progress_note"],
        generator=CapturingGenerator(),
    ).run()
    assert captured == [(0, 5), (1, 5), (2, 5)]


def test_stub_day_index_missing_dates_defaults_to_zero(tmp_path: Path):
    pd = _patient_dict()
    pd["documents"] = [{
        "document_id": "doc-ENC-1-progress_note-day-0",
        "task_type": "progress_note",
        "loinc_code": "11506-3",
        "format_type": "free_text",
        "narrative": None,
    }]
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(json.dumps(pd, ensure_ascii=False))

    captured: list[int] = []

    class CapturingGenerator:
        def generate(self, ctx, spec):
            captured.append(ctx.day_index)
            return NarrativeOutput(raw_text="x")

    TemplateNarrativePass(
        cif_dir=str(tmp_path), country="US", tasks=["progress_note"],
        generator=CapturingGenerator(),
    ).run()
    assert captured == [0]


# ─── backward compat (pre-1a structural JSON) ────────────────────────────


def test_old_cif_without_new_fields_defaults_cleanly():
    """Pre-1a JSON: no severity/archetype on encounter, no condition_event,
    missing list keys → sensible defaults, no raise."""
    pd = {
        "patient": {"patient_id": "POP-1", "age": 65, "sex": "M"},
        "encounters": [{"encounter_id": "ENC-1", "encounter_type": "inpatient"}],
        "documents": [],
    }
    ctx = _build_ctx(pd)
    assert ctx.severity == ""
    assert ctx.clinical_course_archetype == ""
    assert ctx.disease_protocol is None
    assert ctx.encounter_protocol is None
    assert ctx.narrative_spine is None
    assert ctx.vitals == []
    assert ctx.medications == []
    assert ctx.diagnoses == []
    assert ctx.allergies == []
    assert ctx.day_index == 0
    assert ctx.los_days == 1
