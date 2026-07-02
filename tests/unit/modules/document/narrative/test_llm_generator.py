"""Tests for LLMNarrativeGenerator (Task 7 α-min-1; migrated to the N-chain IF).

The CLINOSIM_NARRATIVE_LLM env gate is deleted — opt-in is the explicit
construction of an LLMService. Three paths:
- llm=None → template output, generator=template_fallback, WARN
- llm configured → apply_replacement_strategy (MockProvider-backed LLMService)
- strategy raises → template output, generator=template_fallback, WARN
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clinosim.modules.document.narrative.llm_generator import LLMNarrativeGenerator
from clinosim.modules.llm_service.engine import LLMService
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
) -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key="admission_hp",
        loinc_code="34117-2",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp", "us"),
        generation_frequency="admission_once",
        composition_sections=("hpi", "assessment_and_plan"),
        stage2_strategy=stage2_strategy,
        llm_enabled_sections=llm_enabled_sections,
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


def _mock_template_generator(sections: dict[str, str] | None = None) -> MagicMock:
    tg = MagicMock()
    tg.generate.return_value = NarrativeOutput(
        sections=sections or {"hpi": "template hpi", "assessment_and_plan": "template a&p"},
        metadata={"generator": "template", "lang": "ja"},
        facts_used=["ctx.day_index"],
    )
    return tg


class _RaisingProvider:
    """Provider whose complete() always raises (exhausts LLMService retries)."""

    def complete(self, prompt, model=None, max_tokens=1000, system_prompt="",
                 temperature=0.4, stop_sequences=None):
        raise RuntimeError("LLM connection refused")

    def health_check(self) -> bool:
        return False


def _mock_llm_service(provider=None) -> LLMService:
    return LLMService(
        mode="llm",
        narrative_provider=provider if provider is not None else MockProvider(),
        narrative_model_map={"medium": "mock"},
        provider_name_narrative="mock",
        retry_attempts=1,
        retry_backoff_seconds=0.0,
    )


# ─────────────────────────────────────────────────────────────────
# Path 1 — llm=None → template fallback + WARN
# ─────────────────────────────────────────────────────────────────


def test_llm_generator_no_service_falls_back_to_template_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tg = _mock_template_generator()
    gen = LLMNarrativeGenerator(template_generator=tg, llm=None)
    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    ctx = _make_ctx()

    with caplog.at_level(logging.WARNING):
        result = gen.generate(ctx, spec)

    tg.generate.assert_called_once_with(ctx, spec)
    assert result.sections["hpi"] == "template hpi"
    assert result.metadata["generator"] == "template_fallback"
    assert any("LLMService" in rec.message or "llm" in rec.message.lower()
               for rec in caplog.records)


def test_llm_generator_default_llm_is_none() -> None:
    gen = LLMNarrativeGenerator()
    assert gen.llm is None


# ─────────────────────────────────────────────────────────────────
# Path 2 — llm configured → strategy applied
# ─────────────────────────────────────────────────────────────────


def test_llm_generator_with_service_replaces_enabled_sections() -> None:
    tg = _mock_template_generator({"hpi": "template hpi", "assessment_and_plan": "template a&p"})
    provider = MockProvider()
    gen = LLMNarrativeGenerator(template_generator=tg, llm=_mock_llm_service(provider))
    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    ctx = _make_ctx()

    result = gen.generate(ctx, spec)

    assert provider.call_count == 1
    assert result.sections["hpi"].startswith("[Mock LLM response")
    assert result.sections["assessment_and_plan"] == "template a&p"
    assert result.metadata["generator"] == "llm"


def test_llm_generator_template_only_spec_keeps_template_metadata() -> None:
    """template_only spec: no LLM call, metadata stays 'template' (not 'llm')."""
    tg = _mock_template_generator()
    provider = MockProvider()
    gen = LLMNarrativeGenerator(template_generator=tg, llm=_mock_llm_service(provider))
    spec = _make_spec(stage2_strategy="template_only")
    ctx = _make_ctx()

    result = gen.generate(ctx, spec)

    assert provider.call_count == 0
    assert result.sections["hpi"] == "template hpi"
    assert result.metadata["generator"] == "template"


def test_llm_generator_template_seed_prompt_contains_seed_text() -> None:
    """Idea D pin: the seed prompt sent to the provider embeds template text."""
    tg = _mock_template_generator({"hpi": "UNIQUE-SEED-TEXT", "assessment_and_plan": "a&p"})
    provider = MockProvider()
    gen = LLMNarrativeGenerator(template_generator=tg, llm=_mock_llm_service(provider))
    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    ctx = _make_ctx()

    gen.generate(ctx, spec)

    assert "UNIQUE-SEED-TEXT" in provider.last_prompt


# ─────────────────────────────────────────────────────────────────
# Path 3 — strategy raises → template fallback + WARN
# ─────────────────────────────────────────────────────────────────


def test_llm_generator_provider_raises_falls_back_to_template_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tg = _mock_template_generator()
    gen = LLMNarrativeGenerator(
        template_generator=tg, llm=_mock_llm_service(_RaisingProvider())
    )
    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    ctx = _make_ctx()

    with caplog.at_level(logging.WARNING):
        result = gen.generate(ctx, spec)

    assert result.sections["hpi"] == "template hpi"
    assert result.metadata["generator"] == "template_fallback"
    assert any("fall" in rec.message.lower() for rec in caplog.records)


# ─────────────────────────────────────────────────────────────────
# Cache wiring
# ─────────────────────────────────────────────────────────────────


def test_llm_generator_uses_narrative_cache_across_calls() -> None:
    """Second generate() with the same clinical bucket hits the layer-1 cache."""
    tg = _mock_template_generator()
    provider = MockProvider()
    gen = LLMNarrativeGenerator(template_generator=tg, llm=_mock_llm_service(provider))
    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    ctx = _make_ctx()

    gen.generate(ctx, spec)
    gen.generate(ctx, spec)

    assert provider.call_count == 1  # second call served from NarrativeCache


# ─────────────────────────────────────────────────────────────────
# I-2 (N-chain adv-1) — generator-level fallback counters
# ─────────────────────────────────────────────────────────────────


def test_llm_generator_counters_all_calls_fail(caplog: pytest.LogCaptureFixture) -> None:
    """Provider down: every eligible doc falls back → llm_docs stays 0,
    fallback_docs == eligible doc count, exception reasons sampled."""
    tg = _mock_template_generator()
    gen = LLMNarrativeGenerator(
        template_generator=tg, llm=_mock_llm_service(_RaisingProvider())
    )
    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    ctx = _make_ctx()

    with caplog.at_level(logging.WARNING):
        gen.generate(ctx, spec)
        gen.generate(ctx, spec)

    assert gen.llm_docs == 0
    assert gen.eligible_docs == 2
    assert gen.fallback_docs == 2
    assert gen.fallback_reasons  # at least one sampled reason
    assert any("LLM connection refused" in r or "LLMCompletionError" in r
               for r in gen.fallback_reasons)


def test_llm_generator_counters_healthy_provider() -> None:
    """Healthy provider: llm_docs counts eligible docs, fallback_docs stays 0."""
    tg = _mock_template_generator()
    gen = LLMNarrativeGenerator(template_generator=tg, llm=_mock_llm_service())
    eligible_spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    template_only_spec = _make_spec(stage2_strategy="template_only")
    ctx = _make_ctx()

    gen.generate(ctx, eligible_spec)
    gen.generate(ctx, template_only_spec)  # not eligible — no counter change

    assert gen.llm_docs == 1
    assert gen.eligible_docs == 1
    assert gen.fallback_docs == 0
    assert gen.fallback_reasons == []


def test_llm_generator_fallback_reasons_capped_at_3() -> None:
    """Reason sampling is bounded (~3) so manifests stay small."""
    tg = _mock_template_generator()
    gen = LLMNarrativeGenerator(
        template_generator=tg, llm=_mock_llm_service(_RaisingProvider())
    )
    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    ctx = _make_ctx()

    for _ in range(6):
        gen.generate(ctx, spec)

    assert gen.fallback_docs == 6
    assert len(gen.fallback_reasons) <= 3


def test_llm_generator_env_gate_removed() -> None:
    """The CLINOSIM_NARRATIVE_LLM env gate is deleted (silent-switch class)."""
    import clinosim.modules.document.narrative.llm_generator as mod

    assert not hasattr(mod, "is_llm_enabled")
