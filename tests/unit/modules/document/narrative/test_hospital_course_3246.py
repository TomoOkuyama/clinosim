"""The discharge summary writes the hospital course (Issue #3246).

The hospital course names the main treatments by drug tier, the procedures
with their dates, the complications with the hospital day of onset, the
significant results with the drugs given for them, the medication changes
from admission and the condition at discharge; the discharge diagnoses list
the diagnoses that arose during the stay; a readmission says so in the H&P
HPI and the summary, without describing the previous stay.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative import _hospital_course as hc
from clinosim.modules.document.narrative._localization import _localize_complication
from clinosim.modules.document.narrative._medication_plan import medication_plan_rules
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers._shared_helpers import procedure_prose_name
from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import (
    build_discharge_diagnoses,
    build_hospital_course,
)
from clinosim.modules.document.narrative.renderers.section_builders.hpi import build_hpi
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

_ADMIT = datetime(2025, 12, 4, 17, 0)


def _ctx(lang: str, *, doc: DocumentType = DocumentType.DISCHARGE_SUMMARY, **fields) -> NarrativeContext:
    p = PatientProfile(patient_id="pt-3246")
    p.age = 70
    p.sex = "M"
    enc = SimpleNamespace(
        encounter_id="enc-3246",
        admission_datetime=_ADMIT,
        discharge_datetime=datetime(2025, 12, 10, 10, 0),
        encounter_type=SimpleNamespace(value="inpatient"),
        primary_diagnosis="Acute myocardial infarction",
        discharge_disposition=fields.pop("disposition", "snf"),
    )
    base = dict(
        patient=p,
        encounter=enc,
        encounter_type=enc.encounter_type,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=6,
        los_days=6,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=doc,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )
    base.update(fields)
    return NarrativeContext(**base)


def _mar(drug_id: str, name: str, route: str, when: str, status: str = "given") -> dict:
    return {"drug_id": drug_id, "drug_name": name, "route": route, "actual_datetime": when, "status": status}


def _lab(name: str, value: float, unit: str, flag: str, when: str) -> dict:
    return {"lab_name": name, "value": value, "unit": unit, "flag": flag, "result_datetime": when}


def _pci(lang: str) -> dict:
    return {
        "procedure_type": "pci",
        "procedure_code": "K5491" if lang == "ja" else "92920",
        "procedure_code_jp": "K5491",
        "procedure_code_us": "92920",
        "start_datetime": "2025-12-05T09:00:00",
    }


def _stay(lang: str, **extra) -> NarrativeContext:
    return _ctx(
        lang,
        procedures=[_pci(lang)],
        complications_events=[
            {"name": "acute_kidney_injury", "onset_day": 2, "onset_datetime": "2025-12-06T12:00:00"},
        ],
        lab_results=[
            _lab("K", 4.1, "mmol/L", "", "2025-12-04T18:00:00"),
            _lab("K", 6.9, "mmol/L", "critical", "2025-12-05T17:40:00"),
        ],
        medications=[
            _mar("heparin", "Heparin", "IV", "2025-12-04T18:30:00"),
            _mar("calcium_gluconate", "Calcium Gluconate 1 g IV", "IV", "2025-12-05T18:30:00"),
            _mar("patiromer", "Patiromer 8.4 g PO", "PO", "2025-12-05T18:50:00"),
            _mar("ceftriaxone", "Ceftriaxone", "IV", "2025-12-06T09:00:00"),
            _mar("normal_saline", "Normal Saline", "IV", "2025-12-04T18:00:00"),
        ],
        **extra,
    )


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_course_names_procedure_complication_and_treated_potassium(lang: str) -> None:
    text, facts = build_hospital_course(TemplateNarrativeGenerator(), _stay(lang))
    # Procedure with its date.
    assert (
        t("hospital_course.procedure_with_date", lang, name=procedure_prose_name(_pci(lang), lang), date="2025-12-05")
        in text
    )
    # Complication with its hospital day (onset_day 2 = hospital day 3).
    aki = _localize_complication("acute_kidney_injury", lang)
    assert t("hospital_course.complication_with_onset", lang, day=3, label=aki) in text
    # K 6.9 with its day and the drugs given for it, not the earlier heparin.
    assert "6.9" in text
    lab_part = text.split(t("hospital_course.labs_line", lang, list="").rstrip(".。"))[1]
    assert ("Calcium Gluconate" if lang == "en" else "グルコン酸カルシウム") in lab_part
    assert ("Patiromer" if lang == "en" else "パチロマー") in lab_part
    assert ("Heparin" if lang == "en" else "ヘパリン") not in lab_part
    for fact in ("ctx.procedures", "ctx.complications_events", "ctx.lab_results", "ctx.medications"):
        assert fact in facts


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_treatments_grouped_by_tier_without_fluids(lang: str) -> None:
    sentence, _ = hc.treatments_sentence(_stay(lang))
    anti = t("hospital_course.treatment_tier.antimicrobial", lang)
    antico = t("hospital_course.treatment_tier.anticoagulant", lang)
    assert anti in sentence and antico in sentence
    assert sentence.index(anti) < sentence.index(antico)  # tier order
    assert ("Normal Saline" if lang == "en" else "生理食塩液") not in sentence
    # Patiromer (oral, no tier) is not a main treatment.
    assert ("Patiromer" if lang == "en" else "パチロマー") not in sentence


def test_held_and_unrecorded_doses_are_not_treatments() -> None:
    ctx = _ctx("en", medications=[_mar("ceftriaxone", "Ceftriaxone", "IV", "2025-12-05T09:00:00", status="held")])
    assert hc.treatments_sentence(ctx) == ("", "")


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_medication_changes_from_admission(lang: str) -> None:
    home = [
        {"drug_id": "candesartan", "drug_name": "Candesartan", "drug_name_ja": "カンデサルタン", "dose": "8mg"},
        {"drug_id": "amlodipine", "drug_name": "Amlodipine", "drug_name_ja": "アムロジピン", "dose": "5mg"},
    ]
    discharge = [
        {"drug_id": "amlodipine", "drug_name": "Amlodipine", "dose": "10mg PO daily"},
        {"drug_id": "apixaban", "drug_name": "Apixaban", "dose": "5mg PO BID"},
    ]
    ctx = _ctx(lang, home_medications_at_admission=home, discharge_medications=discharge)
    sentence, fact = hc.medication_changes_sentence(ctx)
    assert fact == "ctx.discharge_medications"
    assert t("hospital_course.med_started", lang, list="") in sentence
    assert ("Apixaban" if lang == "en" else "アピキサバン") in sentence
    assert ("Candesartan" if lang == "en" else "カンデサルタン") in sentence
    assert "5mg" in sentence and "10mg" in sentence


def test_medication_changes_silent_without_admission_snapshot_or_prescription() -> None:
    discharge = [{"drug_id": "apixaban", "drug_name": "Apixaban", "dose": "5mg"}]
    assert hc.medication_changes_sentence(_ctx("en", discharge_medications=discharge)) == ("", "")
    assert hc.medication_changes_sentence(_ctx("en", home_medications_at_admission=[])) == ("", "")


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_discharge_condition(lang: str) -> None:
    adl = [{"date": "2025-12-04", "barthel_score": 40}]
    sentence, _ = hc.discharge_condition_sentence(_ctx(lang, adl_assessments=adl))
    assert t("hospital_course.barthel", lang, score=40) in sentence
    assert ("skilled nursing" if lang == "en" else "施設退院") in sentence


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_complications_are_secondary_discharge_diagnoses(lang: str) -> None:
    ctx = _ctx(
        lang,
        diagnoses=[{"discharge_diagnosis_code": "I21.9", "discharge_diagnosis_system": "icd-10-cm"}],
        working_diagnoses=[{"disease_id": "N17.9", "onset_day": 4}],
        complications_events=[
            {"name": "acute_kidney_injury", "onset_day": 2},
            {"name": "stroke", "onset_day": 5},
        ],
    )
    text, facts = build_discharge_diagnoses(TemplateNarrativeGenerator(), ctx)
    assert "I21.9" in text
    secondary = text.split("Secondary diagnoses:" if lang == "en" else "副病名:")[1]
    assert "N17" in secondary
    # AKI is already the coded N17.9; stroke has no Condition and no code.
    aki = _localize_complication("acute_kidney_injury", lang)
    assert t("list_sep.serial", lang) + aki not in secondary and not secondary.strip().startswith(
        aki + t("list_sep.serial", lang)
    )
    assert ("stroke" if lang == "en" else "脳卒中") in secondary
    assert "ctx.working_diagnoses" in facts


def test_single_diagnosis_without_complications_is_unchanged() -> None:
    ctx = _ctx("en", diagnoses=[{"discharge_diagnosis_code": "I21.9", "discharge_diagnosis_system": "icd-10-cm"}])
    text, _ = build_discharge_diagnoses(TemplateNarrativeGenerator(), ctx)
    assert "Secondary" not in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_readmission_in_hpi_and_summary(lang: str) -> None:
    gen = TemplateNarrativeGenerator()
    sentence = t("hospital_course.readmission_numbered", lang, n=1)
    hp = _ctx(lang, doc=DocumentType.ADMISSION_HP, day_index=0, is_readmission=True, readmission_number=1)
    hpi, facts = build_hpi(gen, hp)
    assert hpi.endswith(sentence) and "ctx.is_readmission" in facts
    course, _ = build_hospital_course(gen, _ctx(lang, is_readmission=True, readmission_number=1))
    assert sentence in course
    # A first admission says nothing about readmission.
    assert sentence not in build_hpi(gen, _ctx(lang, doc=DocumentType.ADMISSION_HP, day_index=0))[0]
    assert sentence not in build_hospital_course(gen, _ctx(lang))[0]


def test_context_projects_readmission() -> None:
    record = {"is_readmission": True, "readmission_number": 2, "patient": None}
    ctx = build_narrative_context(record, None, DocumentType.ADMISSION_HP, 0, "US")
    assert ctx.is_readmission is True and ctx.readmission_number == 2


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_every_treatment_tier_has_a_label(lang: str) -> None:
    for tier in medication_plan_rules().tiers:
        label = t(f"hospital_course.treatment_tier.{tier.name}", lang)
        assert label and not label.startswith("hospital_course."), tier.name


def test_rules_load() -> None:
    rules = hc.hospital_course_rules()
    assert rules.notable_labs.responses["K"].high is not None


def test_narrative_pass_projects_readmission(tmp_path) -> None:
    from clinosim.modules.document import specs_for_country
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass

    spec = next(s for s in specs_for_country("US") if s.type_key == "admission_hp")
    patient = {
        "patient": {"patient_id": "POP-1", "age": 65, "sex": "M"},
        "is_readmission": True,
        "readmission_number": 1,
    }
    encounter = {"encounter_id": "ENC-1", "encounter_type": "inpatient"}
    ctx = TemplateNarrativePass(cif_dir=str(tmp_path), country="US")._build_context(patient, encounter, spec, "en")
    assert ctx.is_readmission is True and ctx.readmission_number == 1


def test_maintenance_fluids_are_not_treatments() -> None:
    ctx = _ctx(
        "en",
        medications=[
            _mar("lactated_ringer_solution", "Lactated Ringer's", "IV", "2025-12-05T09:00:00"),
            _mar("normal_saline", "Normal Saline", "IV", "2025-12-05T09:00:00"),
        ],
    )
    assert hc.treatments_sentence(ctx) == ("", "")
