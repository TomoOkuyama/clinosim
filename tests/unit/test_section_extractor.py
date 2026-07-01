"""Regression tests for section_extractor dict/dataclass dual-access (AD-65 Task 3 fix).

TemplateNarrativePass._build_context populates ctx.encounter / ctx.patient with
plain dicts parsed from structural CIF JSON. section_extractor._facts_for_section
used to read them via bare ``getattr(dict, key, default)``, which always falls
through to ``default`` for a dict — silently emptying section_facts["hpi"] and
section_facts["past_medical_history"] (PR-90 class silent-no-op; no test failure
today only because template_generator doesn't yet consume section_facts).
"""

import pytest

from clinosim.modules.document import specs_for_country
from clinosim.modules.document.narrative.passes import TemplateNarrativePass


def _admission_hp_spec():
    specs = [s for s in specs_for_country("US") if s.type_key == "admission_hp"]
    assert specs, "admission_hp spec must be registered for US"
    return specs[0]


@pytest.mark.unit
def test_section_extractor_populates_hpi_facts_from_dict_backed_context(tmp_path):
    """extract_for_composition must see admission_diagnosis_code even when
    ctx.encounter is a plain dict (the production shape from parsed CIF JSON)."""
    patient_dict = {
        "patient": {"patient_id": "POP-1", "age": 65, "sex": "M", "chronic_conditions": []},
    }
    encounter_dict = {
        "encounter_id": "ENC-1",
        "encounter_type": {"value": "inpatient"},
        "admission_diagnosis_code": "I21.4",
    }
    spec = _admission_hp_spec()
    pass_ = TemplateNarrativePass(cif_dir=str(tmp_path), country="US")
    ctx = pass_._build_context(patient_dict, encounter_dict, spec, "en")

    assert "hpi" in ctx.section_facts
    hpi_facts = ctx.section_facts["hpi"].facts
    assert any(f.key == "diagnosis.admission_icd" and f.value == "I21.4" for f in hpi_facts), (
        f"expected admission_diagnosis_code fact in hpi section, got {hpi_facts}"
    )


@pytest.mark.unit
def test_section_extractor_populates_past_medical_history_from_dict_backed_context(tmp_path):
    patient_dict = {
        "patient": {
            "patient_id": "POP-1",
            "age": 72,
            "sex": "F",
            "chronic_conditions": [],
        },
    }
    encounter_dict = {
        "encounter_id": "ENC-1",
        "encounter_type": {"value": "inpatient"},
        "admission_diagnosis_code": "I21.4",
    }
    spec = _admission_hp_spec()
    pass_ = TemplateNarrativePass(cif_dir=str(tmp_path), country="US")
    ctx = pass_._build_context(patient_dict, encounter_dict, spec, "en")

    assert "past_medical_history" in ctx.section_facts
    pmh_facts = ctx.section_facts["past_medical_history"].facts
    assert any(f.key == "patient.age" and f.value == "72" for f in pmh_facts), (
        f"expected patient.age fact in past_medical_history section, got {pmh_facts}"
    )
    assert any(f.key == "patient.sex" and f.value == "F" for f in pmh_facts)
