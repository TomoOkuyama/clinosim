"""Verify narrative_seed_bundle.yaml (both langs) references the new
`considered_but_not_prescribed` context key and carries the
drug_safety avoidance instruction."""

from __future__ import annotations

from pathlib import Path

import yaml

_PROMPT_ROOT = Path(__file__).resolve().parents[2] / "clinosim" / "modules" / "llm_service" / "prompts"


def _load(lang: str) -> dict:
    with (_PROMPT_ROOT / lang / "narrative_seed_bundle.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_en_bundle_version_at_or_above_14() -> None:
    assert _load("en")["version"] >= 14


def test_ja_bundle_version_at_or_above_14() -> None:
    assert _load("ja")["version"] >= 14


def test_en_bundle_lists_session_104_patient_profile_keys() -> None:
    system = _load("en")["system"]
    for key in ("patient_demographics", "patient_biometrics", "health_literacy_tag"):
        assert key in system, f"EN bundle missing session-104 context key: {key}"
    # Rule 6 is the health-literacy tone guardrail.
    assert "HEALTH-LITERACY TONE" in system


def test_ja_bundle_lists_session_104_patient_profile_keys() -> None:
    system = _load("ja")["system"]
    for key in ("patient_demographics", "patient_biometrics", "health_literacy_tag"):
        assert key in system, f"JA bundle missing session-104 context key: {key}"
    assert "HEALTH-LITERACY TONE" in system


def test_en_bundle_lists_considered_but_not_prescribed_context_key() -> None:
    system = _load("en")["system"]
    assert "considered_but_not_prescribed" in system


def test_ja_bundle_lists_considered_but_not_prescribed_context_key() -> None:
    system = _load("ja")["system"]
    assert "considered_but_not_prescribed" in system


def test_en_bundle_instructs_llm_to_surface_avoidance_in_ap() -> None:
    system = _load("en")["system"]
    assert "avoided due to concurrent" in system
    # The "NEVER invent avoidances" grounding guard must be present.
    assert "NEVER invent" in system or "never invent" in system.lower()


def test_ja_bundle_instructs_llm_to_surface_avoidance_in_ap() -> None:
    system = _load("ja")["system"]
    assert "併用禁忌のため" in system
    assert "回避" in system


def test_extra_context_builder_emits_considered_but_not_prescribed() -> None:
    """_build_extra_context serializes ctx.safety_skips into the prompt payload."""
    from types import SimpleNamespace

    from clinosim.modules.document.narrative.replacement_strategy import (
        _build_extra_context,
    )

    ctx = SimpleNamespace(
        patient=None,
        encounter=None,
        encounter_type=None,
        target_lang="ja",
        disease_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=1,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        complications_occurred=[],
        working_diagnoses=[],
        safety_skips=[
            {
                "considered": "Ibuprofen",
                "considered_ja": "イブプロフェン",
                "avoided_due_to": "Warfarin",
                "avoided_due_to_ja": "ワルファリン",
                "rationale_en": "risk",
                "rationale_ja": "リスク",
                "substituted_with": "Acetaminophen",
                "substituted_with_ja": "アセトアミノフェン",
                "context": "pain_management",
                "severity": "contraindicated",
            }
        ],
    )
    spec = SimpleNamespace(type_key="progress_note")
    extra = _build_extra_context(ctx, spec, template_section_names=set())
    assert "considered_but_not_prescribed" in extra
    text = extra["considered_but_not_prescribed"]
    assert "イブプロフェン" in text
    assert "ワルファリン" in text
    assert "アセトアミノフェン" in text


def test_extra_context_builder_skips_when_no_safety_skips() -> None:
    from types import SimpleNamespace

    from clinosim.modules.document.narrative.replacement_strategy import (
        _build_extra_context,
    )

    ctx = SimpleNamespace(
        patient=None,
        encounter=None,
        encounter_type=None,
        target_lang="en",
        disease_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="mild",
        day_index=0,
        los_days=2,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        complications_occurred=[],
        working_diagnoses=[],
        safety_skips=[],
    )
    spec = SimpleNamespace(type_key="progress_note")
    extra = _build_extra_context(ctx, spec, template_section_names=set())
    assert "considered_but_not_prescribed" not in extra


# ─────────────────────────────────────────────────────────────────
# v16 (session 104 post-verify defect fixes, Issues #1167 + #1168)
#   #1167 — admission_hp assessment_and_plan heading list splits by locale
#   #1168 — Rule 5 Section A covers disease-persistence + stage descriptors
# ─────────────────────────────────────────────────────────────────


def test_en_bundle_admission_hp_headings_have_en_locale_branch() -> None:
    """The EN bundle's admission_hp guidance MUST enumerate an EN-side
    heading set alongside (or instead of) the JA-Kanji verbatim list —
    otherwise the LLM leaks bare Kanji (評価 / 薬物療法 / 検査) into
    English admission-H&P narratives (Issue #1167 root cause).
    """
    system = _load("en")["system"]
    # Locate the admission_hp block
    hp_start = system.find("### admission_hp")
    hp_end = system.find("### discharge_summary", hp_start)
    assert hp_start >= 0 and hp_end > hp_start, "admission_hp block missing"
    hp_block = system[hp_start:hp_end]
    # Assert BOTH locale headings are present in the block
    assert "target_language=ja" in hp_block, "admission_hp block missing target_language=ja variant"
    assert "target_language=en" in hp_block, (
        "admission_hp block missing target_language=en variant "
        "(Issue #1167 — LLM leaks JA Kanji headings without this branch)"
    )
    assert "Assessment" in hp_block and "Medications" in hp_block, (
        "admission_hp block missing EN-side heading vocabulary"
    )


def test_ja_bundle_admission_hp_headings_have_en_locale_branch() -> None:
    """Symmetric guard for the JA bundle."""
    system = _load("ja")["system"]
    hp_start = system.find("### admission_hp")
    hp_end = system.find("### discharge_summary", hp_start)
    assert hp_start >= 0 and hp_end > hp_start
    hp_block = system[hp_start:hp_end]
    assert "target_language=ja" in hp_block
    assert "target_language=en" in hp_block
    assert "Assessment" in hp_block and "Medications" in hp_block


def test_ja_bundle_section_a_covers_persistence_and_stage_descriptors() -> None:
    """JA bundle Rule 5 Section A must enumerate `intermittent`,
    `persistent`, `stage`, `level`, `grade` explicitly. Session-104
    H100 verify (JP p=100 s=125) surfaced 280+ EN leaks of these
    tokens into JA narratives; pre-fix Section A only covered
    mild/moderate/severe/very-severe/critical."""
    system = _load("ja")["system"]
    # Extract Section A
    a_start = system.find("A. Severity")
    b_start = system.find("B.", a_start)
    assert a_start >= 0 and b_start > a_start, "Section A missing"
    section_a = system[a_start:b_start]
    for token in ("intermittent", "persistent", "stage", "level", "grade"):
        assert token in section_a, f"Issue #1168 regression: Section A missing token '{token}'"
    # Case-insensitive rule must be stated (Mild / MILD / mild all → 軽度)
    assert "case-insensitive" in section_a.lower(), "Section A missing case-insensitivity clause"
    # Compound severity example
    assert "軽度持続" in section_a or "Mild persistent" in section_a
