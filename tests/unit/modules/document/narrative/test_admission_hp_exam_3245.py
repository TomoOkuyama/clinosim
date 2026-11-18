"""The admission H&P writes the admitting disease's exam and only what was
known when it was written (Issues #3245, #3241, #3227).

The exam findings (disease_exam.yaml) are the disease's, in English and
Japanese; the vitals, labs and newborn screening results are those recorded
by the note's authored time; a stroke exam states the focal deficit with the
NIHSS score on the admission day and an AF patient has an irregularly
irregular pulse.
"""

from __future__ import annotations

import glob
import os
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative._as_of import recorded_by
from clinosim.modules.document.narrative.context import newborn_workup_known_at
from clinosim.modules.document.narrative.renderers._disease_exam import apply_exam_rules, stroke_deficit
from clinosim.modules.document.narrative.renderers.section_builders.assessment_and_plan import (
    build_assessment_and_plan,
)
from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_physical_exam
from clinosim.modules.document.narrative.renderers.section_builders.hpi import build_hpi
from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
    build_admission_results,
    build_physical_examination,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.reference_data_loaders import load_disease_exam
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2025, 11, 20, 18, 35)
_GEN = TemplateNarrativeGenerator()


def _vital(when: datetime, **values: Any) -> dict:
    reading = {
        "timestamp": when.isoformat(),
        "systolic_bp": 128,
        "diastolic_bp": 76,
        "heart_rate": 84,
        "respiratory_rate": 16,
        "spo2": 97.0,
        "temperature_celsius": 36.8,
        "consciousness_level": "A",
    }
    reading.update(values)
    return reading


def _ctx(
    disease: str | None,
    lang: str,
    *,
    severity: str = "moderate",
    vitals: list | None = None,
    authored: datetime | None = None,
    day_index: int = 0,
    chronic: list[ChronicCondition] | None = None,
    doc_type: DocumentType = DocumentType.ADMISSION_HP,
    **extra: Any,
) -> NarrativeContext:
    encounter = SimpleNamespace(
        encounter_id="ENC-77",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=_ADMIT,
        chief_complaint="Chest pain",
        chief_complaint_ja="胸痛",
        severity=severity,
        triage_data=None,
    )
    ctx = NarrativeContext(
        patient=PatientProfile(
            patient_id="PT-1", sex="M", date_of_birth=date(1950, 5, 1), chronic_conditions=chronic or []
        ),
        encounter=encounter,
        encounter_type=encounter.encounter_type,
        disease_protocol=load_disease_protocol(disease) if disease else None,
        encounter_protocol=None,
        clinical_course_archetype="smooth_recovery",
        severity=severity,
        day_index=day_index,
        los_days=5,
        vitals=vitals if vitals is not None else [_vital(_ADMIT)],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=doc_type,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        orders=[],
        authored_datetime=authored,
        **extra,
    )
    return ctx


def _exam(ctx: NarrativeContext) -> str:
    return build_physical_examination(_GEN, ctx)[0]


# ── disease_exam.yaml ────────────────────────────────────────────────────


def test_every_disease_has_an_authored_exam_in_both_languages() -> None:
    data = load_disease_exam()
    disease_dir = os.path.join(os.path.dirname(__file__), "../../../../../clinosim/modules/disease/reference_data")
    ids = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(disease_dir, "*.yaml"))}
    assert ids == set(data.diseases), ids ^ set(data.diseases)

    def texts(entry: dict) -> list[dict]:
        return [entry] if "en" in entry else list(entry.values())

    for disease, entry in data.diseases.items():
        for system, text in entry.systems.items():
            for lang_map in texts(text):
                assert lang_map.get("ja"), (disease, system)
        if entry.general:
            assert entry.general.get("ja"), disease


def test_no_disease_yaml_carries_the_placeholder_assessment() -> None:
    disease_dir = os.path.join(os.path.dirname(__file__), "../../../../../clinosim/modules/disease/reference_data")
    for path in glob.glob(os.path.join(disease_dir, "*.yaml")):
        text = open(path, encoding="utf-8").read()
        assert "初期診断確定" not in text, path


# ── #3245: disease exam, HPI, plan ───────────────────────────────────────


def test_en_acute_mi_exam_has_a_cardiovascular_finding_and_no_placeholder() -> None:
    text = _exam(_ctx("acute_mi", "en"))
    assert "Cardiovascular: regular rhythm, no new murmur or rub" in text, text
    assert "no additional exam findings recorded" not in text, text
    assert text.startswith("Vital signs: BP 128/76"), text


def test_ja_hip_fracture_exam_has_the_limb_findings_and_the_plan_names_the_surgery() -> None:
    ctx = _ctx("hip_fracture", "ja")
    text = _exam(ctx)
    assert "運動器: 患側下肢の短縮と外旋" in text and "四肢: 足背動脈を触知" in text, text
    assert "項部硬直" not in text, text
    ctx.procedures = [
        SimpleNamespace(
            encounter_id="ENC-77",
            category_code="387713003",
            procedure_type="orif_hip",
            start_datetime=datetime(2025, 11, 22, 9, 0),
            procedure_name="観血的整復固定術",
        )
    ]
    plan = build_assessment_and_plan(_GEN, ctx)[0]
    assert "手術予定" in plan, plan


def test_plan_states_the_code_status_the_record_assigned() -> None:
    ctx = _ctx("acute_mi", "en", code_status="304253006")
    plan = build_assessment_and_plan(_GEN, ctx)[0]
    assert "Code status: Not for resuscitation" in plan, plan


def test_en_hpi_has_demographics_the_typed_onset_and_the_ros() -> None:
    ctx = _ctx("hip_fracture", "en")
    text = build_hpi(_GEN, ctx)[0]
    assert text.startswith("75 y/o male patient. Chief complaint: Chest pain. "), text
    assert "Injured today" in text and "ROS: " in text, text


def test_exam_drops_a_clause_the_quoted_vitals_contradict() -> None:
    quiet = _ctx("heart_failure_exacerbation", "en", vitals=[_vital(_ADMIT, heart_rate=80)])
    assert "tachycardia" not in _exam(quiet) and "S3 gallop" in _exam(quiet)
    fast = _ctx("heart_failure_exacerbation", "en", vitals=[_vital(_ADMIT, heart_rate=118)])
    assert "tachycardia, S3 gallop" in _exam(fast)


def test_consciousness_clause_follows_the_avpu_of_the_reading() -> None:
    ctx = _ctx("acute_mi", "en", vitals=[_vital(_ADMIT, consciousness_level="P")])
    assert "responds only to painful stimulus" in _exam(ctx)


# ── #3241: what existed at the authored time ─────────────────────────────


def test_hp_does_not_quote_a_vital_sign_taken_after_it_was_written() -> None:
    first_next_day = datetime(2025, 11, 21, 0, 2)
    ctx = _ctx("acute_mi", "en", vitals=[_vital(first_next_day, heart_rate=99)], authored=_ADMIT)
    text = _exam(ctx)
    assert "HR 99" not in text and not text.startswith("Vital signs"), text
    assert "General:" in text, text


def test_hp_quotes_the_first_reading_taken_by_its_authored_time() -> None:
    ctx = _ctx(
        "acute_mi",
        "en",
        vitals=[
            _vital(datetime(2025, 11, 20, 17, 0), heart_rate=90),
            _vital(datetime(2025, 11, 20, 20, 0), heart_rate=70),
        ],
        authored=_ADMIT,
    )
    assert "HR 90/min" in _exam(ctx) and "HR 70" not in _exam(ctx)


def test_recorded_by_keeps_records_up_to_the_time() -> None:
    rows = [{"t": "2025-11-20T10:00:00"}, {"t": "2025-11-20T12:00:00"}, {"t": None}]
    assert recorded_by(rows, datetime(2025, 11, 20, 11, 0), "t") == [rows[0], rows[2]]
    assert recorded_by(rows, None, "t") == rows


def test_newborn_summary_drops_results_dated_after_the_note() -> None:
    workup = {
        "is_neonate": True,
        "apgar_1min": 8,
        "apgar_5min": 9,
        "bilirubin_peak": 12.2,
        "bilirubin_series": [
            {"timestamp": "2026-01-27T10:00:00", "day": 1, "value_mg_dl": 4.1},
            {"timestamp": "2026-01-29T10:00:00", "day": 3, "value_mg_dl": 12.2},
        ],
        "cchd_ru_spo2": 97,
        "cchd_le_spo2": 97,
        "cchd_at": "2026-01-27T10:09:00",
        "has_aabr": True,
        "has_metabolic": True,
        "has_vitamin_k": True,
        "has_ophthalmic": True,
        "event_times": {
            "aabr": "2026-01-27T10:09:00",
            "metabolic": "2026-01-30T10:00:00",
            "vitamin_k": "2026-01-26T11:00:00",
            "ophthalmic": "2026-01-26T10:30:00",
        },
    }
    known = newborn_workup_known_at(workup, datetime(2026, 1, 26, 10, 9))
    assert known["apgar_1min"] == 8 and known["has_vitamin_k"] is False  # given after the note (11:00)
    assert known["has_ophthalmic"] is False
    assert not known["has_aabr"] and not known["has_metabolic"]
    assert known["bilirubin_peak"] is None and known["cchd_ru_spo2"] is None
    later = newborn_workup_known_at(workup, datetime(2026, 1, 28, 0, 0))
    assert later["has_aabr"] and not later["has_metabolic"] and later["bilirubin_peak"] == 4.1
    assert newborn_workup_known_at(workup, None) is workup


def test_admission_results_cite_only_the_results_back_at_the_note_time() -> None:
    lab = {
        "lab_name": "Troponin_I",
        "value": 0.9,
        "unit": "ng/mL",
        "flag": "H",
        "result_datetime": "2025-11-20T19:10:00",
    }
    ctx = _ctx("acute_mi", "en", authored=_ADMIT)
    ctx.lab_results = [lab]
    ctx.orders = [SimpleNamespace(order_type="lab")]
    assert build_admission_results(_GEN, ctx)[0] == "Laboratory: results pending"
    ctx = _ctx("acute_mi", "en", authored=datetime(2025, 11, 20, 21, 0))
    ctx.lab_results = [lab]
    text = build_admission_results(_GEN, ctx)[0]
    assert text.startswith("Laboratory (abnormal): troponin I 0.900 ng/mL") and "[H]" in text, text


def test_admission_results_include_the_imaging_reports_issued_by_the_note_time() -> None:
    study = {
        "description": "ECG_12lead",
        "report": {
            "impression_text": "ST-T changes suggesting acute myocardial ischemia.",
            "issued_datetime": "2025-11-20T19:00:00",
        },
    }
    late = {
        "description": "Chest_Xray_PA",
        "report": {"impression_text": "No acute process.", "issued_datetime": "2025-11-20T23:00:00"},
    }
    ctx = _ctx("acute_mi", "en", authored=datetime(2025, 11, 20, 21, 0), imaging_studies=[study, late])
    text = build_admission_results(_GEN, ctx)[0]
    assert "ST-T changes" in text and "No acute process" not in text, text


def test_the_hp_is_authored_after_the_admission_work_up() -> None:
    from clinosim.modules.document.engine import _EncounterFacts, _plan_admission_once
    from clinosim.modules.document.narrative.registry import load_document_type_specs

    specs = load_document_type_specs()
    hp, nursing = specs[DocumentType.ADMISSION_HP], specs[DocumentType.ADMISSION_NURSING_ASSESSMENT]
    facts = _EncounterFacts(
        record=None,
        encounter=None,
        encounter_id="E",
        pid="P",
        admission_dt=_ADMIT,
        discharge_dt=datetime(2025, 11, 25, 10, 0),
        los_days=5,
        config=None,
    )
    plan = _plan_admission_once(hp, facts)[0]
    assert plan.authored == "2025-11-20T21:35:00" and plan.period_start == _ADMIT.isoformat()
    assert _plan_admission_once(nursing, facts)[0].authored == _ADMIT.isoformat()
    brief = _EncounterFacts(**{**facts.__dict__, "discharge_dt": datetime(2025, 11, 20, 19, 0)})
    assert _plan_admission_once(hp, brief)[0].authored == "2025-11-20T19:00:00"


# ── #3227: stroke deficit and AF rhythm ──────────────────────────────────


@pytest.mark.parametrize("disease", ["cerebral_infarction", "hemorrhagic_stroke"])
@pytest.mark.parametrize("lang", ["en", "ja"])
def test_stroke_exam_states_the_deficit_with_the_nihss_and_never_denies_it(disease: str, lang: str) -> None:
    ctx = _ctx(disease, lang, severity="severe")
    for text in (_exam(ctx), build_ed_physical_exam(_GEN, ctx)[0]):
        assert "NIHSS" in text, text
        assert ("hemiplegia" in text) if lang == "en" else ("完全片麻痺" in text), text
        for denial in ("麻痺なし", "特記の身体所見なし", "No focal findings", "no focal", "項部硬直なし"):
            assert denial not in text, text


def test_stroke_deficit_is_consistent_per_encounter_and_follows_the_severity() -> None:
    first = stroke_deficit(_ctx("cerebral_infarction", "en"), with_nihss=True)
    assert first == stroke_deficit(_ctx("cerebral_infarction", "en"), with_nihss=True)
    score = int(first.rsplit("NIHSS ", 1)[1])
    assert 5 <= score <= 15
    assert 16 <= int(stroke_deficit(_ctx("cerebral_infarction", "en", severity="severe"), with_nihss=True)[-2:]) <= 25
    side = "right" if "right hemiparesis" in first else "left"
    ja = stroke_deficit(_ctx("cerebral_infarction", "ja"), with_nihss=True)
    assert ("右片麻痺" in ja) == (side == "right")
    # the weakness side and the accompanying deficit agree: aphasia with right weakness, neglect with left
    assert ("aphasia" in first) == (side == "right") and ("neglect" in first) == (side == "left")
    assert stroke_deficit(_ctx("acute_mi", "en"), with_nihss=True) == ""


def test_stroke_exam_on_a_later_day_has_the_deficit_without_the_score() -> None:
    ctx = _ctx("cerebral_infarction", "ja", day_index=6, vitals=[_vital(_ADMIT)])
    text = apply_exam_rules(ctx, {"neurological": "麻痺なし"}, admission_day=False)["neurological"]
    assert "片麻痺" in text and "NIHSS" not in text and "麻痺なし" not in text, text


def _af(stage: str) -> list[ChronicCondition]:
    return [ChronicCondition(code="I48.91", stage=stage)]


def test_af_admission_has_an_irregularly_irregular_pulse() -> None:
    fast = [_vital(_ADMIT, heart_rate=142)]
    assert "irregularly irregular rhythm, tachycardia, no murmur" in _exam(
        _ctx("atrial_fibrillation_rvr", "en", vitals=fast)
    )
    assert "脈は不整（絶対性不整脈）、頻脈、心雑音なし" in _exam(_ctx("atrial_fibrillation_rvr", "ja", vitals=fast))


def test_chronic_af_replaces_the_regular_rhythm_unless_paroxysmal() -> None:
    chronic = _ctx("acute_mi", "en", chronic=_af("Permanent"))
    text = _exam(chronic)
    assert "Cardiovascular: irregularly irregular rhythm, no new murmur or rub" in text, text
    ja = apply_exam_rules(
        _ctx("acute_mi", "ja", chronic=_af("Persistent")), {"cardiovascular": "整、心雑音なし"}, admission_day=False
    )
    assert ja["cardiovascular"] == "脈は不整（絶対性不整脈）、心雑音なし"
    assert "regular rhythm, no new murmur" in _exam(_ctx("acute_mi", "en", chronic=_af("Paroxysmal")))
    only = apply_exam_rules(_ctx("elective_knee_arthroplasty", "en", chronic=_af("Permanent")), {}, admission_day=True)
    assert only["cardiovascular"] == "irregularly irregular rhythm"
