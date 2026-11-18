"""Newborn documents use newborn content (Issue #3260 parts a and c).

A neonate (under 28 days old at the encounter) has no smoking, alcohol or
occupation history, no adult neurological exam and no adult ADL / fall-risk
scales. The H&P records the birth history and caregiver instead, the exam
resolver picks the newborn exam set (fontanelle, primitive reflexes,
umbilicus, jaundice, hips) with the jaundice finding read from the bilirubin
measured by the note's time, and the nursing record states that the newborn
depends fully on care. A JA drug display that already names the generic keeps
its brand name.
"""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from clinosim.locale.free_text import localize_drug_name
from clinosim.modules.document.narrative._narrative_utils import is_neonate
from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
    build_adl_assessment,
    build_risk_assessments,
)
from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
    build_physical_examination,
    build_social_history,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import ChronicCondition, ContactInfo, PatientProfile

pytestmark = pytest.mark.unit

_CJK = re.compile(r"[぀-ヿ㐀-鿿]")
_BILI = [
    {"day": 1, "timestamp": "2026-01-27T10:00:00", "value_mg_dl": 4.1},
    {"day": 2, "timestamp": "2026-01-28T10:00:00", "value_mg_dl": 8.8},
    {"day": 3, "timestamp": "2026-01-29T10:00:00", "value_mg_dl": 12.2},
]


def _ctx(
    lang: str = "ja",
    *,
    dob: str = "2026-01-26",
    admitted: str = "2026-01-26T10:09:00",
    day_index: int = 0,
    authored: datetime | None = None,
    adult: bool = False,
) -> NarrativeContext:
    patient = PatientProfile(patient_id="POP-1-BABY")
    patient.age = 40 if adult else 0
    patient.date_of_birth = "1986-01-01" if adult else dob  # type: ignore[assignment]
    patient.occupation = "office_worker" if adult else "infant"
    patient.smoking_status = "never"
    patient.alcohol_use = "none"
    if not adult:
        patient.perinatal_history = [ChronicCondition(code="Z38.0", onset_date=None)]  # type: ignore[arg-type]
        patient.contact = ContactInfo(emergency_contact_relationship="MTH")
    return NarrativeContext(
        patient=patient,
        encounter={"encounter_id": "ENC-1", "admission_datetime": admitted, "admit_source": "born"},
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="",
        day_index=day_index,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        rehab_sessions=[],
        allergies=[],
        document_type=DocumentType.ADMISSION_HP,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        authored_datetime=authored,
        newborn_workup={}
        if adult
        else {"is_neonate": True, "apgar_1min": 8, "apgar_5min": 10, "bilirubin_series": list(_BILI)},
    )


@pytest.fixture(scope="module")
def gen() -> TemplateNarrativeGenerator:
    return TemplateNarrativeGenerator()


# ── is_neonate: age in days at the encounter ─────────────────────────────


def test_is_neonate_by_age_in_days_at_the_encounter() -> None:
    assert is_neonate(_ctx(admitted="2026-01-26T10:09:00"))
    assert is_neonate(_ctx(admitted="2026-02-22T10:00:00"))  # day 27
    assert not is_neonate(_ctx(admitted="2026-02-23T10:00:00"))  # day 28
    assert not is_neonate(_ctx(adult=True))


# ── social history ───────────────────────────────────────────────────────


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_newborn_social_history_has_birth_history_not_smoking(gen, lang) -> None:
    text, _ = build_social_history(gen, _ctx(lang))
    for word in ("喫煙", "飲酒", "職業", "Smoking", "Alcohol", "Occupation"):
        assert word not in text
    if lang == "ja":
        assert text == "出生歴: 院内出生、Apgar 8点(1分)/10点(5分)、出生時データの記録なし; 養育者: 母"
    else:
        assert (
            text == "Birth history: born in this hospital, Apgar 8 (1 min) / 10 (5 min), birth data not recorded; "
            "Caregiver: mother"
        )
        assert not _CJK.search(text)


def test_adult_social_history_unchanged(gen) -> None:
    text, _ = build_social_history(gen, _ctx("ja", adult=True))
    assert "喫煙歴" in text and "飲酒歴" in text


# ── newborn exam set ─────────────────────────────────────────────────────


def test_newborn_exam_ja_has_newborn_findings_and_no_adult_neuro(gen) -> None:
    text, _ = build_physical_examination(gen, _ctx("ja"))
    for finding in ("大泉門", "モロー反射", "臍", "股関節", "黄疸なし"):
        assert finding in text, finding
    assert "項部硬直" not in text and "麻痺" not in text and "意識清明" not in text


def test_newborn_exam_en_has_newborn_findings(gen) -> None:
    text, _ = build_physical_examination(gen, _ctx("en"))
    for finding in ("fontanelle", "Moro", "Umbilic", "Hips", "No jaundice"):
        assert finding in text, finding
    assert "no additional exam findings" not in text
    assert not _CJK.search(text)


def test_newborn_jaundice_follows_the_bilirubin_known_at_the_note(gen) -> None:
    day3 = _ctx("ja", day_index=3, authored=datetime(2026, 1, 29, 12, 0))
    text, _ = build_physical_examination(gen, day3)
    assert "黄疸なし" not in text and "黄疸" in text
    day2 = _ctx("ja", day_index=2, authored=datetime(2026, 1, 28, 12, 0))
    text2, _ = build_physical_examination(gen, day2)
    assert "黄疸なし" not in text2 and text2 != text
    # Before the first measurement there is no jaundice to report.
    day1_early = _ctx("ja", day_index=1, authored=datetime(2026, 1, 27, 8, 0))
    text1, _ = build_physical_examination(gen, day1_early)
    assert "黄疸なし" in text1


def test_adult_exam_still_uses_the_adult_baseline(gen) -> None:
    text, _ = build_physical_examination(gen, _ctx("ja", adult=True))
    # Issue #3245: an adult admission without a diagnosis has the general appearance only.
    assert "大泉門" not in text and "一般状態:" in text and "神経:" not in text


# ── nursing ADL / risk ───────────────────────────────────────────────────


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_newborn_nursing_adl_and_risk_are_neonatal(gen, lang) -> None:
    adl, _ = build_adl_assessment(gen, _ctx(lang))
    risk, _ = build_risk_assessments(gen, _ctx(lang))
    assert "自立" not in adl and "independent" not in adl
    assert "評価中" not in risk and "pending" not in risk
    if lang == "ja":
        assert "新生児" in adl and "新生児" in risk
    else:
        assert "newborn" in adl.lower() and "newborn" in risk.lower()
        assert not _CJK.search(adl + risk)


def test_adult_nursing_fallbacks_unchanged(gen) -> None:
    adl, _ = build_adl_assessment(gen, _ctx("ja", adult=True))
    assert adl == "ADL：自立（問題なし）"


# ── (c) brand inside a display that already names the generic ───────────


def test_brand_kept_when_the_display_already_names_the_generic() -> None:
    out = localize_drug_name("ケイツーシロップ (メナテトレノン 2 mg 経口)", "ja")
    assert out == "ケイツーシロップ (メナテトレノン 2 mg 経口)"
    assert out.count("メナテトレノン") == 1


def test_brand_alone_still_resolves_to_the_generic() -> None:
    assert localize_drug_name("ケイツーシロップ", "ja") == "メナテトレノン"
