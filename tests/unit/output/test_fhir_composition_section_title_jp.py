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

from clinosim.modules.output._fhir_composition import (
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
    ],
)
def test_localize_section_title_ja(slug: str, expected: str) -> None:
    """Every slug flagged by iris4h-ai 2026-07-22 feedback resolves to a
    Japanese clinical-chart display."""
    assert _localize_section_title(slug, "ja") == expected


def test_localize_section_title_en_returns_slug_unchanged() -> None:
    """English locale keeps the raw slug (unchanged pre-fix behaviour)."""
    assert _localize_section_title("adl_assessment", "en") == "adl_assessment"
    assert _localize_section_title("hpi", "en") == "hpi"


def test_localize_section_title_unknown_slug_falls_back_to_slug() -> None:
    """Unknown slugs pass through unchanged so a new template section still
    emits — silent-no-op deferral is intentional (adding a new slug is a
    dict edit, not an emitter change). Guards against a future emitter
    that would crash on missing translation."""
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


def test_en_composition_section_titles_preserve_english_slugs() -> None:
    """Regression pin: US locale keeps the pre-fix English slugs on
    ``section[].title`` — Issue #360 G3 must not alter US behaviour."""
    doc = _minimal_doc()
    doc["language"] = "en"
    sections = {"hpi": "History of present illness."}
    res = _build_composition_generic(doc, sections, lang="en")
    assert res["section"][0]["title"] == "hpi"
