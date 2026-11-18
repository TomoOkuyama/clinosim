"""The admitted patient's ED note has an HPI and an exam (Issue #3243).

A via-ED admission has no ED-visit protocol, so its ED note used to carry the
severity fallback HPI ("Patient presented with severe symptoms.") and an
exam of the arrival vitals alone. The HPI is now the admitting disease's HPI
(the H&P source) and the exam the disease's day-0 exam after the arrival
vitals, with the clauses the arrival reading contradicts left out.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_physical_exam
from clinosim.modules.document.narrative.renderers.section_builders.hpi import build_hpi
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2025, 11, 20, 18, 35)
_ARRIVAL = datetime(2025, 11, 20, 15, 5)


def _encounter(enc_type: str, arrival_mode: str, cc_ja: str, cc_en: str) -> SimpleNamespace:
    return SimpleNamespace(
        encounter_id="ENC-1",
        encounter_type=SimpleNamespace(value=enc_type),
        admission_datetime=_ADMIT,
        chief_complaint=cc_en,
        chief_complaint_ja=cc_ja,
        chief_complaint_en=cc_en,
        severity="moderate",
        discharge_disposition="home",
        triage_data=SimpleNamespace(level="2", level_system="JTAS", arrival_mode=arrival_mode),
    )


def _vital(when: datetime, **values: float) -> dict:
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
    enc_type: str = "inpatient",
    arrival_mode: str = "walk-in",
    vitals: list | None = None,
    archetype: str = "smooth_recovery",
    cc: tuple[str, str] = ("胸痛", "Chest pain"),
) -> NarrativeContext:
    return NarrativeContext(
        patient=PatientProfile(patient_id="PT-1", sex="M", date_of_birth=date(1950, 5, 1)),
        encounter=_encounter(enc_type, arrival_mode, *cc),
        encounter_type=SimpleNamespace(value=enc_type),
        disease_protocol=load_disease_protocol(disease) if disease else None,
        encounter_protocol=None,
        clinical_course_archetype=archetype,
        severity=severity,
        day_index=0,
        los_days=5,
        vitals=vitals if vitals is not None else [_vital(_ARRIVAL)],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ED_NOTE,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        orders=[],
    )


# ── HPI ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_admitted_ed_hpi_is_not_the_severity_fallback(lang: str) -> None:
    text, facts = build_hpi(TemplateNarrativeGenerator(), _ctx("hip_fracture", lang, cc=("転倒", "Fall")))
    assert text not in {"Patient presented with moderate symptoms.", "中等度の症状で受診。"}, text
    assert any(f.startswith("disease_protocol.narrative.hpi_template") for f in facts), facts


def test_admitted_ed_hpi_ja_has_the_injury_onset_and_history() -> None:
    text, _ = build_hpi(TemplateNarrativeGenerator(), _ctx("hip_fracture", "ja", cc=("転倒", "Fall")))
    assert "本日受傷" in text, text
    assert "75歳" in text or "75 歳" in text, text


def test_admitted_ed_hpi_en_uses_the_onset_type_of_the_disease() -> None:
    """An injury is not described as symptoms developing over several days."""
    text, facts = build_hpi(TemplateNarrativeGenerator(), _ctx("hip_fracture", "en", cc=("転倒", "Fall")))
    assert "Injured today and presented" in text, text
    assert "disease_protocol.narrative.hpi_template.onset_type.injury" in facts


@pytest.mark.parametrize(
    ("lang", "ambulance", "neutral"),
    [("ja", "救急搬入", "救急外来を受診"), ("en", "brought in by ambulance", "presented to the emergency department")],
)
def test_admitted_ed_hpi_does_not_say_ambulance_for_a_walk_in(lang: str, ambulance: str, neutral: str) -> None:
    ctx = _ctx("hip_fracture", lang, severity="severe", arrival_mode="walk-in", cc=("転倒", "Fall"))
    text, _ = build_hpi(TemplateNarrativeGenerator(), ctx)
    assert ambulance not in text and neutral in text, text


@pytest.mark.parametrize(("lang", "ambulance"), [("ja", "救急搬入"), ("en", "brought in by ambulance")])
def test_admitted_ed_hpi_keeps_the_ambulance_arrival(lang: str, ambulance: str) -> None:
    ctx = _ctx("hip_fracture", lang, severity="severe", arrival_mode="ambulance", cc=("転倒", "Fall"))
    text, _ = build_hpi(TemplateNarrativeGenerator(), ctx)
    assert ambulance in text, text


def test_admission_hp_hpi_is_unchanged_by_the_arrival_mode() -> None:
    """The arrival-mode wording applies to the ED note only."""
    ctx = _ctx("hip_fracture", "ja", severity="severe", arrival_mode="walk-in", cc=("転倒", "Fall"))
    ed_text, _ = build_hpi(TemplateNarrativeGenerator(), ctx)
    hp_ctx = NarrativeContext(**{**ctx.__dict__, "document_type": DocumentType.ADMISSION_HP})
    hp_text, _ = build_hpi(TemplateNarrativeGenerator(), hp_ctx)
    assert "救急搬入" in hp_text and "救急搬入" not in ed_text


# ── Exam ─────────────────────────────────────────────────────────────────


def test_admitted_ed_exam_ja_is_the_day0_exam_after_the_arrival_vitals() -> None:
    vitals = [_vital(_ARRIVAL, heart_rate=121), _vital(datetime(2025, 11, 21, 0, 2), heart_rate=83)]
    text, facts = build_ed_physical_exam(
        TemplateNarrativeGenerator(), _ctx("heart_failure_exacerbation", "ja", vitals=vitals)
    )
    assert text.startswith("来院時所見: "), text
    assert "HR 121" in text and "HR 83" not in text, text
    assert "一般状態: 意識清明、中等度の苦痛様" in text, text
    assert "循環器: 頻脈、III 音（ギャロップ）を聴取、頸静脈怒張" in text, text
    assert "特記" not in text, text
    assert text.endswith("。"), text
    assert "physical_exam_findings.disease_exam" in facts


def test_admitted_ed_exam_drops_tachycardia_when_the_arrival_hr_is_normal() -> None:
    text, _ = build_ed_physical_exam(
        TemplateNarrativeGenerator(),
        _ctx("heart_failure_exacerbation", "ja", severity="mild", vitals=[_vital(_ARRIVAL, heart_rate=84)]),
    )
    assert "頻脈" not in text, text
    assert "循環器: III 音（ギャロップ）を聴取、頸静脈怒張" in text, text


@pytest.mark.parametrize(("sbp", "kept"), [(128, False), (82, True)])
def test_admitted_ed_exam_hypotension_follows_the_arrival_bp(sbp: int, kept: bool) -> None:
    vitals = [_vital(_ARRIVAL, heart_rate=118, systolic_bp=sbp)]
    text, _ = build_ed_physical_exam(
        TemplateNarrativeGenerator(), _ctx("sepsis", "ja", severity="severe", vitals=vitals)
    )
    assert "頻脈" in text, text
    assert ("血圧低下" in text) is kept, text


def test_admitted_ed_exam_rewrites_alert_when_the_arrival_avpu_is_not_alert() -> None:
    """The consciousness clause agrees with the arrival AVPU even when the
    arrival was the calendar day before the admission."""
    arrival = datetime(2025, 11, 19, 23, 10)
    ctx = _ctx("acute_mi", "ja", vitals=[_vital(arrival, consciousness_level="V")])
    ctx = NarrativeContext(**{**ctx.__dict__, "encounter": _encounter("inpatient", "walk-in", "胸痛", "Chest pain")})
    ctx.encounter.admission_datetime = datetime(2025, 11, 20, 2, 40)
    text, _ = build_ed_physical_exam(TemplateNarrativeGenerator(), ctx)
    assert "意識清明" not in text, text


def test_admitted_ed_exam_en_is_the_disease_exam_after_the_arrival_vitals() -> None:
    """Issue #3245: the English note writes the disease's exam in English
    (without the clause the arrival reading contradicts), never a CJK text."""
    text, _ = build_ed_physical_exam(
        TemplateNarrativeGenerator(),
        _ctx("heart_failure_exacerbation", "en", vitals=[_vital(_ARRIVAL, heart_rate=84)]),
    )
    assert text.startswith("On arrival: ") and "HR 84" in text, text
    assert "S3 gallop" in text and "tachycardia" not in text, text
    assert "No focal" not in text and not any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for ch in text)


def test_admitted_ed_exam_without_arrival_vitals_is_not_recorded() -> None:
    ward = [_vital(datetime(2025, 11, 21, 0, 2))]
    text, _ = build_ed_physical_exam(TemplateNarrativeGenerator(), _ctx("acute_mi", "ja", vitals=ward))
    assert text == "来院時の身体所見: 記載なし"


def test_ed_visit_sent_home_exam_is_unchanged() -> None:
    ctx = _ctx("acute_mi", "en", enc_type="emergency", vitals=[_vital(_ARRIVAL, heart_rate=84)])
    text, _ = build_ed_physical_exam(TemplateNarrativeGenerator(), ctx)
    assert text == "On arrival: BP 128/76 mmHg, HR 84 bpm, RR 16 /min, SpO2 97%, T 36.8°C. No focal findings on exam."
