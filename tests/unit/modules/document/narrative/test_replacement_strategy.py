"""Tests for apply_replacement_strategy (Task 7, Tier 1 #3 α-min-1).

Tests cover:
- template_only strategy returns template unchanged (no provider call)
- template_seed strategy passes template text as seed to provider
- unknown strategy falls back to template (safe default)
- only llm_enabled_sections are replaced
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.replacement_strategy import (
    LLMProvider,
    apply_replacement_strategy,
)
from clinosim.types.document import DocumentType, FormatType, NarrativeContext, NarrativeOutput


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _make_spec(
    stage2_strategy: str = "template_only",
    llm_enabled_sections: tuple[str, ...] = (),
    format_type: FormatType = FormatType.COMPOSITION,
) -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key="admission_hp",
        loinc_code="34117-2",
        display_en="History & Physical",
        display_ja="入院時病歴・身体所見",
        format_type=format_type,
        countries_supported=("jp", "us"),
        generation_frequency="once_on_admission",
        composition_sections=("hpi", "assessment_and_plan"),
        stage2_strategy=stage2_strategy,
        llm_enabled_sections=llm_enabled_sections,
    )


def _make_template_output(sections: dict[str, str] | None = None) -> NarrativeOutput:
    return NarrativeOutput(
        sections=sections or {
            "hpi": "Template HPI text",
            "assessment_and_plan": "Template A&P text",
        },
        metadata={"generator": "template", "lang": "ja"},
        facts_used=["ctx.day_index"],
    )


def _make_ctx() -> NarrativeContext:
    patient = SimpleNamespace(age=55, sex="M", chronic_conditions=[])
    encounter = SimpleNamespace(encounter_id="enc-test")
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ADMISSION_HP,
        target_lang="ja",
        locale="jp",
    )


def _mock_provider(return_value: str = "LLM-generated mock content") -> MagicMock:
    provider = MagicMock()
    provider.generate.return_value = return_value
    return provider


# ─────────────────────────────────────────────────────────────────
# template_only strategy
# ─────────────────────────────────────────────────────────────────


def test_template_only_strategy_returns_template_unchanged() -> None:
    """template_only: template output returned verbatim, provider not called."""
    spec = _make_spec(stage2_strategy="template_only")
    template_output = _make_template_output()
    provider = _mock_provider()
    ctx = _make_ctx()

    result = apply_replacement_strategy(template_output, ctx, spec, provider)

    assert result is template_output
    provider.generate.assert_not_called()


def test_template_only_strategy_preserves_all_fields() -> None:
    """template_only: all NarrativeOutput fields preserved exactly."""
    spec = _make_spec(stage2_strategy="template_only")
    template_output = _make_template_output({"hpi": "original hpi"})
    ctx = _make_ctx()
    provider = _mock_provider()

    result = apply_replacement_strategy(template_output, ctx, spec, provider)

    assert result.sections["hpi"] == "original hpi"
    assert result.metadata["generator"] == "template"


# ─────────────────────────────────────────────────────────────────
# template_seed strategy
# ─────────────────────────────────────────────────────────────────


def test_template_seed_strategy_passes_template_as_seed_to_provider() -> None:
    """template_seed: provider.generate receives a prompt containing the template text."""
    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi",),
    )
    template_output = _make_template_output({"hpi": "Template HPI text", "assessment_and_plan": "A&P"})
    ctx = _make_ctx()
    provider = _mock_provider()

    apply_replacement_strategy(template_output, ctx, spec, provider)

    provider.generate.assert_called_once()
    call_args = provider.generate.call_args[0][0]  # first positional arg = prompt str
    assert "Template HPI text" in call_args  # template seed included in prompt


def test_template_seed_strategy_only_replaces_llm_enabled_sections() -> None:
    """template_seed: only llm_enabled_sections are replaced; others pass through."""
    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi",),
    )
    template_output = _make_template_output({
        "hpi": "Template HPI text",
        "assessment_and_plan": "Template A&P text",
    })
    ctx = _make_ctx()
    provider = _mock_provider("LLM-generated mock content")

    result = apply_replacement_strategy(template_output, ctx, spec, provider)

    # LLM-enabled section replaced
    assert result.sections["hpi"] == "LLM-generated mock content"
    # Non-LLM section unchanged
    assert result.sections["assessment_and_plan"] == "Template A&P text"


def test_template_seed_strategy_calls_provider_per_enabled_section() -> None:
    """template_seed: provider called once per enabled section."""
    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi", "assessment_and_plan"),
    )
    template_output = _make_template_output()
    ctx = _make_ctx()
    provider = _mock_provider()

    apply_replacement_strategy(template_output, ctx, spec, provider)

    assert provider.generate.call_count == 2


# ─────────────────────────────────────────────────────────────────
# Unknown strategy — safe default
# ─────────────────────────────────────────────────────────────────


def test_unknown_strategy_falls_back_to_template() -> None:
    """Unknown stage2_strategy: template output returned (safe default)."""
    spec = _make_spec(stage2_strategy="future_unknown_strategy")
    template_output = _make_template_output()
    ctx = _make_ctx()
    provider = _mock_provider()

    result = apply_replacement_strategy(template_output, ctx, spec, provider)

    assert result is template_output
    provider.generate.assert_not_called()


# ─────────────────────────────────────────────────────────────────
# Cache integration
# ─────────────────────────────────────────────────────────────────


def test_template_seed_strategy_uses_cache_on_hit() -> None:
    """Cache hit: provider not called on second request with same key."""
    from clinosim.modules.document.narrative.cache import NarrativeCache
    cache = NarrativeCache()

    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi",),
    )
    template_output = _make_template_output({"hpi": "Template HPI text"})
    ctx = _make_ctx()
    provider = _mock_provider("LLM-generated mock content")

    # First call — cache miss → provider invoked
    apply_replacement_strategy(
        template_output, ctx, spec, provider,
        cache_get=cache.get, cache_put=cache.put,
    )
    assert provider.generate.call_count == 1

    # Second call — same context → cache hit → provider NOT invoked again
    apply_replacement_strategy(
        template_output, ctx, spec, provider,
        cache_get=cache.get, cache_put=cache.put,
    )
    assert provider.generate.call_count == 1  # still 1, not 2
