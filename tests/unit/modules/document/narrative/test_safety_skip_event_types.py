"""Test the four `event_type` cadences in `considered_but_not_prescribed`
context rendering (Issue #1403).

Covers:
- ``avoid`` (legacy pair-conflict skip) — with & without substitute.
- ``hold`` (disease-protocol medication_holds).
- ``substitute`` (pregnancy Cat C/D → Methyldopa; JP postop analgesic sub).
- ``deescalate`` (antibiotic de-escalation on hospital-day N).

Also verifies (a) that a missing/legacy `event_type` defaults to "avoid",
(b) that per-locale cadence phrasing is used (JP vs EN), (c) that a
`stopped_on_day` value flows through to the de-escalate line.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from clinosim.modules.document.narrative.replacement_strategy import _build_extra_context
from clinosim.types.document import DocumentType


def _make_ctx(
    safety_skips: list[dict],
    target_lang: str = "en",
    doc_type: str = "admission_hp",
) -> SimpleNamespace:
    """Minimum-viable ctx shape for `_build_extra_context` — only the
    fields the safety-skip rendering path reads are populated."""
    encounter = SimpleNamespace(
        encounter_id="ENC-1",
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        encounter_type=SimpleNamespace(value="inpatient"),
        primary_diagnosis="N17.9",
    )
    return SimpleNamespace(
        patient=None,
        encounter=encounter,
        encounter_type=encounter.encounter_type,
        disease_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=5,
        target_lang=target_lang,
        locale=target_lang,
        vitals=[],
        lab_results=[],
        medications=[],
        procedures=[],
        complications_occurred=[],
        working_diagnoses=[],
        discharge_medications=[],
        document_type=(DocumentType.ADMISSION_HP if doc_type == "admission_hp" else DocumentType.PROGRESS_NOTE),
        safety_skips=safety_skips,
    )


class _Spec:
    def __init__(self, type_key: str) -> None:
        self.type_key = type_key


def _render(safety_skips: list[dict], target_lang: str = "en") -> str:
    ctx = _make_ctx(safety_skips, target_lang=target_lang)
    extra = _build_extra_context(ctx, _Spec("admission_hp"))
    return extra.get("considered_but_not_prescribed", "")


# ---------------------------------------------------------------------------
# avoid — pair-conflict skip
# ---------------------------------------------------------------------------


def test_avoid_default_when_event_type_absent_en() -> None:
    skip = {
        "considered": "NSAID (Ibuprofen)",
        "avoided_due_to": "Warfarin (bleeding-risk)",
        "substituted_with": "Acetaminophen",
        # event_type absent — must default to "avoid"
    }
    out = _render([skip], target_lang="en")
    assert "avoid: NSAID (Ibuprofen)" in out
    assert "avoided due to concurrent Warfarin" in out
    assert "substituted with Acetaminophen" in out


def test_avoid_no_substitute_ja() -> None:
    skip = {
        "considered_ja": "NSAID",
        "avoided_due_to_ja": "ワルファリン",
        "event_type": "avoid",
    }
    out = _render([skip], target_lang="ja")
    assert "avoid: NSAID" in out
    assert "ワルファリン" in out
    assert "代替薬は選択せず" in out


# ---------------------------------------------------------------------------
# hold — disease-protocol medication_holds
# ---------------------------------------------------------------------------


def test_hold_en() -> None:
    skip = {
        "considered": "Enalapril",
        "avoided_due_to": "AKI (KDIGO 2012 § 3.5.2 RAAS hold)",
        "event_type": "hold",
    }
    out = _render([skip], target_lang="en")
    assert "hold: Enalapril" in out
    assert "held during this admission" in out
    assert "AKI" in out


def test_hold_ja() -> None:
    skip = {
        "considered_ja": "エナラプリル",
        "avoided_due_to_ja": "急性腎障害",
        "event_type": "hold",
    }
    out = _render([skip], target_lang="ja")
    assert "hold: エナラプリル" in out
    assert "急性腎障害" in out
    assert "保留" in out


# ---------------------------------------------------------------------------
# substitute — pregnancy or JP postop analgesic
# ---------------------------------------------------------------------------


def test_substitute_pregnancy_en() -> None:
    skip = {
        "considered": "Amlodipine",
        "avoided_due_to": "active pregnancy",
        "substituted_with": "Methyldopa",
        "event_type": "substitute",
    }
    out = _render([skip], target_lang="en")
    assert "substitute: Amlodipine substituted with Methyldopa" in out
    assert "active pregnancy" in out


def test_substitute_pregnancy_ja() -> None:
    skip = {
        "considered_ja": "アムロジピン",
        "avoided_due_to_ja": "妊娠中",
        "substituted_with_ja": "メチルドパ",
        "event_type": "substitute",
    }
    out = _render([skip], target_lang="ja")
    assert "アムロジピン を メチルドパ に切替" in out
    assert "妊娠中" in out


# ---------------------------------------------------------------------------
# deescalate — antibiotic stewardship
# ---------------------------------------------------------------------------


def test_deescalate_with_day_and_narrower_en() -> None:
    skip = {
        "considered": "Cefazolin 2g",
        "avoided_due_to": "antibiotic stewardship",
        "substituted_with": "Amoxicillin 500mg",
        "event_type": "deescalate",
        "stopped_on_day": 3,
    }
    out = _render([skip], target_lang="en")
    assert "deescalate: Cefazolin 2g discontinued on day 3" in out
    assert "narrowed to Amoxicillin 500mg" in out


def test_deescalate_without_day_ja() -> None:
    skip = {
        "considered_ja": "セファゾリン",
        "avoided_due_to_ja": "抗菌薬スチュワードシップ",
        "substituted_with_ja": "アモキシシリン",
        "event_type": "deescalate",
    }
    out = _render([skip], target_lang="ja")
    assert "deescalate: セファゾリン" in out
    assert "経過中で中止" in out
    assert "アモキシシリン" in out


def test_deescalate_stopped_on_day_ja() -> None:
    skip = {
        "considered_ja": "メロペネム",
        "avoided_due_to_ja": "抗菌薬スチュワードシップ",
        "event_type": "deescalate",
        "stopped_on_day": 5,
    }
    out = _render([skip], target_lang="ja")
    assert "deescalate: メロペネム" in out
    assert "第5病日で中止" in out


# ---------------------------------------------------------------------------
# switch — treatment_modifications stop→start (Issue #1413 default)
# ---------------------------------------------------------------------------


def test_switch_with_day_and_replacement_en() -> None:
    skip = {
        "considered": "Cefazolin 2g",
        "avoided_due_to": "treatment plan change (archetype: treatment_resistant)",
        "substituted_with": "Meropenem 1g",
        "event_type": "switch",
        "stopped_on_day": 3,
    }
    out = _render([skip], target_lang="en")
    assert "switch: Cefazolin 2g discontinued on day 3" in out
    assert "Meropenem 1g started" in out
    # Must NOT assert spectrum direction.
    assert "narrowed" not in out
    assert "de-escalated" not in out
    assert "stewardship" not in out


def test_switch_ja_neutral_phrasing() -> None:
    skip = {
        "considered_ja": "セファゾリン",
        "avoided_due_to_ja": "治療計画変更 (経過型: treatment_resistant)",
        "substituted_with_ja": "メロペネム",
        "event_type": "switch",
        "stopped_on_day": 2,
    }
    out = _render([skip], target_lang="ja")
    assert "switch: セファゾリン" in out
    assert "第2病日で中止" in out
    assert "メロペネム" in out
    # Must NOT assert spectrum direction.
    assert "de-escalate" not in out
    assert "de-escalation" not in out
    assert "狭域" not in out


def test_switch_without_replacement() -> None:
    skip = {
        "considered": "Cefazolin",
        "avoided_due_to": "treatment plan change",
        "event_type": "switch",
    }
    out = _render([skip], target_lang="en")
    assert "switch: Cefazolin discontinued during the stay" in out


# ---------------------------------------------------------------------------
# Mixed batch — all five kinds in one payload render distinctly
# ---------------------------------------------------------------------------


def test_mixed_batch_all_event_types_render_distinct_bullets_en() -> None:
    skips = [
        {"considered": "NSAID", "avoided_due_to": "Warfarin", "event_type": "avoid"},
        {"considered": "Enalapril", "avoided_due_to": "AKI protocol", "event_type": "hold"},
        {
            "considered": "Amlodipine",
            "avoided_due_to": "active pregnancy",
            "substituted_with": "Methyldopa",
            "event_type": "substitute",
        },
        {
            "considered": "Cefazolin",
            "avoided_due_to": "treatment plan change",
            "substituted_with": "Meropenem",
            "event_type": "switch",
            "stopped_on_day": 3,
        },
        {
            "considered": "Vancomycin",
            "avoided_due_to": "antibiotic stewardship",
            "substituted_with": "Cefazolin",
            "event_type": "deescalate",
            "stopped_on_day": 2,
        },
    ]
    out = _render(skips, target_lang="en")
    # Every kind gets a distinct leading marker.
    assert "- avoid: NSAID" in out
    assert "- hold: Enalapril" in out
    assert "- substitute: Amlodipine" in out
    assert "- switch: Cefazolin" in out
    assert "- deescalate: Vancomycin" in out
