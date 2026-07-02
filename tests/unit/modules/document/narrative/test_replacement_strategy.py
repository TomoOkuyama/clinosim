"""Tests for apply_replacement_strategy (Task 7 α-min-1; migrated to N-chain IF).

The local LLMProvider Protocol is deleted — the strategy takes an LLMService
and calls complete_prompt (AD-11). Tests use MockProvider-backed LLMService.
"""
from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.document.narrative.replacement_strategy import (
    apply_replacement_strategy,
)
from clinosim.modules.llm_service.engine import LLMService, LLMTaskType
from clinosim.modules.llm_service.providers import MockProvider
from clinosim.types.document import (
    DocumentType,
    DocumentTypeSpec,
    FormatType,
    NarrativeContext,
    NarrativeOutput,
)

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
        format_type=format_type,
        countries_supported=("jp", "us"),
        generation_frequency="admission_once",
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


def _mock_llm(provider: MockProvider | None = None) -> LLMService:
    return LLMService(
        mode="llm",
        narrative_provider=provider if provider is not None else MockProvider(),
        narrative_model_map={"medium": "mock"},
        provider_name_narrative="mock",
        retry_attempts=1,
        retry_backoff_seconds=0.0,
    )


def _apply(template_output, ctx, spec, llm, **kwargs):
    return apply_replacement_strategy(
        template_output, ctx, spec, llm,
        task_type=LLMTaskType.ADMISSION_HP,
        language=ctx.target_lang,
        **kwargs,
    )


# ─────────────────────────────────────────────────────────────────
# template_only strategy
# ─────────────────────────────────────────────────────────────────


def test_template_only_strategy_returns_template_unchanged() -> None:
    """template_only: template output returned verbatim, LLM not called."""
    spec = _make_spec(stage2_strategy="template_only")
    template_output = _make_template_output()
    provider = MockProvider()
    ctx = _make_ctx()

    result = _apply(template_output, ctx, spec, _mock_llm(provider))

    assert result is template_output
    assert provider.call_count == 0


def test_template_only_strategy_preserves_all_fields() -> None:
    """template_only: all NarrativeOutput fields preserved exactly."""
    spec = _make_spec(stage2_strategy="template_only")
    template_output = _make_template_output({"hpi": "original hpi"})
    ctx = _make_ctx()

    result = _apply(template_output, ctx, spec, _mock_llm())

    assert result.sections["hpi"] == "original hpi"
    assert result.metadata["generator"] == "template"


# ─────────────────────────────────────────────────────────────────
# template_seed strategy
# ─────────────────────────────────────────────────────────────────


def test_template_seed_strategy_passes_template_as_seed_to_llm() -> None:
    """template_seed: the LLM receives a prompt containing the template text."""
    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi",),
    )
    template_output = _make_template_output(
        {"hpi": "Template HPI text", "assessment_and_plan": "A&P"}
    )
    ctx = _make_ctx()
    provider = MockProvider()

    _apply(template_output, ctx, spec, _mock_llm(provider))

    assert provider.call_count == 1
    assert "Template HPI text" in provider.last_prompt  # template seed in prompt


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
    provider = MockProvider()

    result = _apply(template_output, ctx, spec, _mock_llm(provider))

    # LLM-enabled section replaced
    assert result.sections["hpi"].startswith("[Mock LLM response")
    # Non-LLM section unchanged
    assert result.sections["assessment_and_plan"] == "Template A&P text"
    # raw_text / facts_used preserved (unmodified template base)
    assert result.raw_text == template_output.raw_text
    assert result.facts_used == template_output.facts_used


def test_template_seed_strategy_calls_llm_per_enabled_section() -> None:
    """template_seed: one LLM call per enabled section."""
    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi", "assessment_and_plan"),
    )
    template_output = _make_template_output()
    ctx = _make_ctx()
    provider = MockProvider()

    _apply(template_output, ctx, spec, _mock_llm(provider))

    assert provider.call_count == 2


# ─────────────────────────────────────────────────────────────────
# Unknown strategy — safe default
# ─────────────────────────────────────────────────────────────────


def test_unknown_strategy_falls_back_to_template() -> None:
    """Unknown stage2_strategy: template output returned (safe default)."""
    spec = _make_spec(stage2_strategy="future_unknown_strategy")
    template_output = _make_template_output()
    ctx = _make_ctx()
    provider = MockProvider()

    result = _apply(template_output, ctx, spec, _mock_llm(provider))

    assert result is template_output
    assert provider.call_count == 0


# ─────────────────────────────────────────────────────────────────
# Cache integration
# ─────────────────────────────────────────────────────────────────


def test_template_seed_with_empty_llm_enabled_sections_returns_template_unchanged() -> None:
    """If stage2_strategy is template_seed but llm_enabled_sections is empty,
    the strategy must safely return the template output unchanged (no
    LLM call, no section mutation).

    Verifies the invariant documented in _apply_template_seed_strategy:
    'When llm_enabled_sections is empty, no LLM call is made and the
    returned output is byte-identical to template_output (safe no-op).'
    """
    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=(),  # ★ empty
        format_type=FormatType.COMPOSITION,
    )
    template_output = _make_template_output({"section_a": "template content"})
    ctx = _make_ctx()
    provider = MockProvider()  # should NOT be called

    result = _apply(template_output, ctx, spec, _mock_llm(provider))

    assert provider.call_count == 0
    assert result.sections["section_a"] == "template content"


def test_template_seed_strategy_uses_cache_on_hit() -> None:
    """NarrativeCache hit: LLM not called on second request with same key."""
    from clinosim.modules.document.narrative.cache import NarrativeCache
    cache = NarrativeCache()

    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi",),
    )
    template_output = _make_template_output({"hpi": "Template HPI text"})
    ctx = _make_ctx()
    provider = MockProvider()
    llm = _mock_llm(provider)

    # First call — cache miss → LLM invoked
    _apply(template_output, ctx, spec, llm,
           cache_get=cache.get, cache_put=cache.put)
    assert provider.call_count == 1

    # Second call — same context → cache hit → LLM NOT invoked again
    _apply(template_output, ctx, spec, llm,
           cache_get=cache.get, cache_put=cache.put)
    assert provider.call_count == 1  # still 1, not 2


def test_local_llm_provider_protocol_deleted() -> None:
    """N-2: the module-local LLMProvider Protocol is removed (AD-11 unification)."""
    import clinosim.modules.document.narrative.replacement_strategy as mod

    assert not hasattr(mod, "LLMProvider")
