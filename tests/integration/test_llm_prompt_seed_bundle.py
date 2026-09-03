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


def test_en_bundle_version_bumped_to_14() -> None:
    assert _load("en")["version"] == 14


def test_ja_bundle_version_bumped_to_14() -> None:
    assert _load("ja")["version"] == 14


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
    from clinosim.types.document import DocumentType

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
