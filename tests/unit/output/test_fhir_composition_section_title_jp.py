"""Issue #360 G3: Composition.section.title JP localization.

Pins the JP-locale substitution of the raw English slug section titles
(``adl_assessment``, ``hpi``, ``chief_complaint``, ...) with their
Japanese clinical-chart display form.

Concrete failure this test guards
---------------------------------
Before the fix (commit ``8b85ed45``, 2026-07-20), JP output emitted:

    "section": [
      {"title": "adl_assessment", "text": {"div": "..."}},
      {"title": "hpi", "text": {"div": "..."}},
      ...
    ]

iris4h-ai's Clinical Cockpit had to maintain its own English-slug →
Japanese dictionary (33 entries) to render 栄養管理計画書 / 看護記録 /
入院時記録 charts in Japanese. Generator-side substitution moves that
responsibility back to clinosim, matching how JP-CLINS
DISCHARGE_SUMMARY sections already carry Japanese titles.

The fix adds ``_SECTION_TITLE_JA`` (dict[str, str]) and
``_localize_section_title(title, lang)``; the generic Composition
builder invokes it once per section. Unknown slugs pass through
unchanged so a new template section still emits.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.documents.composition import (
    _SECTION_TITLE_JA,
    _build_composition_generic,
    _localize_section_title,
)

pytestmark = pytest.mark.unit


# === _localize_section_title predicate ===


@pytest.mark.parametrize(
    "slug,expected",
    [
        ("adl_assessment", "ADL評価"),
        ("hpi", "現病歴"),
        ("chief_complaint", "主訴"),
        ("past_medical_history", "既往歴"),
        ("physical_examination", "身体所見"),
        ("nursing_history", "看護歴"),
        ("nutrition_assessment", "栄養評価"),
        ("family_history", "家族歴"),
        ("social_history", "社会歴"),
        # Issue #870 — ED / inpatient planning sections
        ("ed_workup", "救急外来での評価"),
        ("disposition", "転帰"),
        ("treatment_plan", "治療計画"),
        ("test_schedule", "検査予定"),
        ("surgery_schedule", "手術予定"),
        ("special_nutrition_management", "特別栄養管理"),
        ("other_plans", "その他の計画"),
        ("estimated_los", "予定入院期間"),
        ("discharge_estimate", "退院見込み"),
        ("explanation_consent", "説明と同意"),
        # Issue #870 — Rehabilitation plan sections
        ("session_frequency", "セッション頻度"),
        ("rehab_team", "リハビリテーションチーム"),
        ("policy", "方針"),
        ("goals", "目標"),
        ("functional_status", "機能状態"),
        ("basic_movement", "基本動作"),
    ],
)
def test_localize_section_title_ja(slug: str, expected: str) -> None:
    """Every slug flagged by iris4h-ai (2026-07-22 + 2026-08-26 feedback) resolves to a
    Japanese clinical-chart display."""
    assert _localize_section_title(slug, "ja") == expected


def test_localize_section_title_en_resolves_via_section_title_en() -> None:
    """Issue #1037: US locale must not emit a bare machine slug as
    ``Composition.section.title``. Explicit ``_SECTION_TITLE_EN`` entries
    take priority."""
    assert _localize_section_title("adl_assessment", "en") == "ADL assessment"
    assert _localize_section_title("hpi", "en") == "History of present illness"
    assert _localize_section_title("hospital_course", "en") == "Hospital course"


def test_localize_section_title_en_humanization_fallback() -> None:
    """A new slug with no explicit English mapping is humanized rather than
    emitted as a machine key (`brand_new_section` → `Brand new section`).
    Prevents future template additions from silently regressing to Issue #1037."""
    assert _localize_section_title("brand_new_section", "en") == "Brand new section"


def test_localize_section_title_en_passthrough_for_titlecase_input() -> None:
    """Sections whose ``title`` is already human-readable (`Findings`,
    `Impression`, or contains a space) pass through unchanged so callers
    that emit their own display are not mangled."""
    assert _localize_section_title("Findings", "en") == "Findings"
    assert _localize_section_title("Impression", "en") == "Impression"
    assert _localize_section_title("Assessment and Plan", "en") == "Assessment and Plan"


def test_localize_section_title_unknown_slug_falls_back_to_slug() -> None:
    """Unknown slugs pass through unchanged for JP so a new template section
    still emits — silent-no-op deferral is intentional. (US path now
    humanizes; see the sibling test above.)"""
    assert _localize_section_title("brand_new_section", "ja") == "brand_new_section"


def test_all_30_iris4h_ai_flagged_slugs_covered() -> None:
    """Coverage guard: every slug listed in the iris4h-ai 2026-07-22
    feedback (verbatim) has an entry in ``_SECTION_TITLE_JA``. Detects a
    future accidental deletion or slug rename that would leak an English
    slug back into JP output."""
    iris4h_ai_flagged_slugs = {
        "adl_assessment",
        "admission_status",
        "allergies",
        "assessment_and_plan",
        "care_plan",
        "chief_complaint",
        "dietary_content",
        "dietitian",
        "discharge_evaluation",
        "discharge_readiness",
        "dysphagia_diet",
        "family_history",
        "hpi",
        "medications_at_home",
        "nursing_diagnosis",
        "nursing_history",
        "nursing_interventions_provided",
        "nutrition_assessment",
        "nutrition_counseling",
        "nutrition_goals",
        "nutrition_risk",
        "nutrition_supply",
        "other_issues",
        "past_medical_history",
        "patient_education",
        "physical_examination",
        "reassessment_timing",
        "risk_assessments",
        "social_history",
        "ward_and_physician",
    }
    missing = iris4h_ai_flagged_slugs - _SECTION_TITLE_JA.keys()
    assert not missing, (
        f"Slugs flagged by iris4h-ai 2026-07-22 feedback but missing from _SECTION_TITLE_JA: {sorted(missing)}"
    )


def test_all_iris4h_ai_2026_08_26_flagged_slugs_covered() -> None:
    """Coverage guard for Issue #870: every slug flagged in the iris4h-ai
    2026-08-26 deploy verify (JP p=10000 s500, 11,536 / 221,265 = 5.2%
    Composition.section.title leaked English snake_case) has an entry in
    ``_SECTION_TITLE_JA``. Same inventory-guard pattern as the 2026-07-22
    coverage — protects against a future accidental delete or slug rename."""
    iris4h_ai_2026_08_26_flagged_slugs = {
        # ED / inpatient planning (top offenders, ~11,144 / 11,536 = 96.6%)
        "ed_workup",
        "disposition",
        "treatment_plan",
        "test_schedule",
        "surgery_schedule",
        "special_nutrition_management",
        "other_plans",
        "estimated_los",
        "discharge_estimate",
        "explanation_consent",
        # Rehabilitation (49 records each)
        "session_frequency",
        "rehab_team",
        "policy",
        "goals",
        "functional_status",
        "basic_movement",
    }
    missing = iris4h_ai_2026_08_26_flagged_slugs - _SECTION_TITLE_JA.keys()
    assert not missing, (
        f"Slugs flagged by iris4h-ai 2026-08-26 feedback but missing from _SECTION_TITLE_JA: {sorted(missing)}"
    )


# === End-to-end via _build_composition_generic ===


def _minimal_doc(loinc: str = "11506-3") -> dict[str, object]:
    return {
        "document_id": f"comp-enc-1-{loinc}",
        "loinc_code": loinc,
        "encounter_id": "enc-1",
        "patient_id": "pt-1",
        "author_practitioner_id": "dr-1",
        "authored_datetime": "2026-06-15T09:00:00+09:00",
        "language": "ja",
    }


def test_jp_composition_section_titles_are_all_japanese() -> None:
    """End-to-end: passing a section dict with English slugs to the generic
    Composition builder yields Japanese titles on every emitted
    ``section[].title``."""
    sections = {
        "hpi": "現病歴の記述",
        "physical_examination": "身体所見の記述",
        "adl_assessment": "ADLの記述",
        "nursing_history": "看護歴の記述",
    }
    res = _build_composition_generic(_minimal_doc(), sections, lang="ja")
    titles = [s["title"] for s in res["section"]]
    assert titles == ["現病歴", "身体所見", "ADL評価", "看護歴"]


def test_en_composition_section_titles_use_human_readable_english() -> None:
    """Issue #1037: US locale must not emit machine slugs (`hpi`,
    `hospital_course`) as ``section[].title``. The end-to-end path resolves
    the slug through ``_SECTION_TITLE_EN`` to a human-readable English
    label."""
    doc = _minimal_doc()
    doc["language"] = "en"
    sections = {
        "hpi": "History of present illness content.",
        "hospital_course": "Course content.",
        "discharge_diagnoses": "Diagnoses.",
        "discharge_medications": "Medications.",
        "discharge_instructions": "Instructions.",
        "follow_up": "Follow-up plan.",
    }
    res = _build_composition_generic(doc, sections, lang="en")
    assert [s["title"] for s in res["section"]] == [
        "History of present illness",
        "Hospital course",
        "Discharge diagnoses",
        "Discharge medications",
        "Discharge instructions",
        "Follow-up",
    ]


def test_issue_870_ed_and_rehab_sections_localize_ja() -> None:
    """Issue #870 end-to-end: an ED-note-shaped `sections` dict and a
    rehab-plan-shaped `sections` dict both yield 100% Japanese section
    titles after this fix."""
    ed_sections = {
        "ed_workup": "ED workup content",
        "disposition": "Discharge home",
    }
    res_ed = _build_composition_generic(_minimal_doc(), ed_sections, lang="ja")
    assert [s["title"] for s in res_ed["section"]] == ["救急外来での評価", "転帰"]

    rehab_sections = {
        "goals": "ADL自立",
        "session_frequency": "週3回",
        "rehab_team": "PT/OT/ST",
        "basic_movement": "端座位保持可",
        "functional_status": "移乗要介助",
    }
    res_rehab = _build_composition_generic(_minimal_doc(), rehab_sections, lang="ja")
    assert [s["title"] for s in res_rehab["section"]] == [
        "目標",
        "セッション頻度",
        "リハビリテーションチーム",
        "基本動作",
        "機能状態",
    ]
