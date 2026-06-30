"""Tests for LLMNarrativeGenerator (Task 7, Tier 1 #3 α-min-1).

Tests cover:
- Default OFF: env var absent → template output returned unchanged
- Opt-in (CLINOSIM_NARRATIVE_LLM=on) with mocked provider
- Provider unavailable → template fallback + warning
- Only llm_enabled_sections are replaced
- metadata records generator=llm / template / template_fallback
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from clinosim.modules.document.narrative.llm_generator import (
    LLMNarrativeGenerator,
    is_llm_enabled,
)
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.types.document import DocumentType, FormatType, NarrativeContext, NarrativeOutput


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
        display_en="History & Physical",
        display_ja="入院時病歴・身体所見",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp", "us"),
        generation_frequency="once_on_admission",
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


def _mock_provider(return_value: str = "LLM-generated mock content") -> MagicMock:
    provider = MagicMock()
    provider.generate.return_value = return_value
    return provider


# ─────────────────────────────────────────────────────────────────
# is_llm_enabled
# ─────────────────────────────────────────────────────────────────


def test_is_llm_enabled_default_off() -> None:
    """No CLINOSIM_NARRATIVE_LLM env var → disabled."""
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("CLINOSIM_NARRATIVE_LLM", None)
        assert is_llm_enabled() is False


def test_is_llm_enabled_on() -> None:
    """CLINOSIM_NARRATIVE_LLM=on → enabled."""
    with patch.dict("os.environ", {"CLINOSIM_NARRATIVE_LLM": "on"}):
        assert is_llm_enabled() is True


def test_is_llm_enabled_case_insensitive() -> None:
    """CLINOSIM_NARRATIVE_LLM=ON or On → enabled (case-insensitive)."""
    with patch.dict("os.environ", {"CLINOSIM_NARRATIVE_LLM": "ON"}):
        assert is_llm_enabled() is True


def test_is_llm_enabled_other_value_off() -> None:
    """CLINOSIM_NARRATIVE_LLM=yes → NOT enabled (only 'on' activates)."""
    with patch.dict("os.environ", {"CLINOSIM_NARRATIVE_LLM": "yes"}):
        assert is_llm_enabled() is False


# ─────────────────────────────────────────────────────────────────
# LLMNarrativeGenerator — default OFF path
# ─────────────────────────────────────────────────────────────────


def test_llm_generator_default_off_returns_template_output_unchanged() -> None:
    """No env var set: generator returns template generator's NarrativeOutput verbatim."""
    tg = _mock_template_generator()
    gen = LLMNarrativeGenerator(template_generator=tg)
    spec = _make_spec()
    ctx = _make_ctx()

    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("CLINOSIM_NARRATIVE_LLM", None)
        result = gen.generate(ctx, spec)

    tg.generate.assert_called_once_with(ctx, spec)
    assert result.sections["hpi"] == "template hpi"
    assert result.metadata["generator"] == "template"


def test_llm_generator_default_off_records_template_metadata() -> None:
    """Default OFF: metadata.generator = 'template'."""
    tg = _mock_template_generator()
    gen = LLMNarrativeGenerator(template_generator=tg)
    spec = _make_spec()
    ctx = _make_ctx()

    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("CLINOSIM_NARRATIVE_LLM", None)
        result = gen.generate(ctx, spec)

    assert result.metadata.get("generator") == "template"


# ─────────────────────────────────────────────────────────────────
# LLMNarrativeGenerator — opt-in path
# ─────────────────────────────────────────────────────────────────


def test_llm_generator_opt_in_calls_provider() -> None:
    """CLINOSIM_NARRATIVE_LLM=on + mocked provider → provider invoked, output updated."""
    tg = _mock_template_generator({"hpi": "template hpi", "assessment_and_plan": "template a&p"})
    provider = _mock_provider()
    gen = LLMNarrativeGenerator(template_generator=tg, provider=provider)
    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi",),
    )
    ctx = _make_ctx()

    with patch.dict("os.environ", {"CLINOSIM_NARRATIVE_LLM": "on"}):
        result = gen.generate(ctx, spec)

    provider.generate.assert_called_once()
    assert result.sections["hpi"] == "LLM-generated mock content"


def test_llm_generator_opt_in_records_llm_metadata() -> None:
    """CLINOSIM_NARRATIVE_LLM=on: metadata.generator = 'llm'."""
    tg = _mock_template_generator()
    provider = _mock_provider()
    gen = LLMNarrativeGenerator(template_generator=tg, provider=provider)
    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    ctx = _make_ctx()

    with patch.dict("os.environ", {"CLINOSIM_NARRATIVE_LLM": "on"}):
        result = gen.generate(ctx, spec)

    assert result.metadata.get("generator") == "llm"


def test_llm_generator_only_replaces_llm_enabled_sections() -> None:
    """Only llm_enabled_sections replaced; others remain template text."""
    tg = _mock_template_generator({
        "hpi": "template hpi",
        "assessment_and_plan": "template a&p",
    })
    provider = _mock_provider()
    gen = LLMNarrativeGenerator(template_generator=tg, provider=provider)
    spec = _make_spec(
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi",),  # only hpi
    )
    ctx = _make_ctx()

    with patch.dict("os.environ", {"CLINOSIM_NARRATIVE_LLM": "on"}):
        result = gen.generate(ctx, spec)

    assert result.sections["hpi"] == "LLM-generated mock content"
    assert result.sections["assessment_and_plan"] == "template a&p"


# ─────────────────────────────────────────────────────────────────
# LLMNarrativeGenerator — provider unavailable
# ─────────────────────────────────────────────────────────────────


def test_llm_generator_provider_unavailable_falls_back_to_template_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Opt-in but provider=None → template output returned + warning logged."""
    tg = _mock_template_generator()
    gen = LLMNarrativeGenerator(template_generator=tg, provider=None)
    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    ctx = _make_ctx()

    with patch.dict("os.environ", {"CLINOSIM_NARRATIVE_LLM": "on"}):
        with caplog.at_level(logging.WARNING):
            result = gen.generate(ctx, spec)

    # Template output preserved
    assert result.sections["hpi"] == "template hpi"
    # Warning logged
    assert any("provider" in rec.message.lower() for rec in caplog.records)
    # Metadata records fallback
    assert result.metadata.get("generator") == "template_fallback"


def test_llm_generator_provider_raises_falls_back_to_template_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Opt-in but provider.generate raises → template output returned + warning logged."""
    tg = _mock_template_generator()
    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("LLM connection refused")
    gen = LLMNarrativeGenerator(template_generator=tg, provider=provider)
    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    ctx = _make_ctx()

    with patch.dict("os.environ", {"CLINOSIM_NARRATIVE_LLM": "on"}):
        with caplog.at_level(logging.WARNING):
            result = gen.generate(ctx, spec)

    assert result.sections["hpi"] == "template hpi"
    assert any("LLM" in rec.message or "provider" in rec.message.lower() for rec in caplog.records)
    assert result.metadata.get("generator") == "template_fallback"


# ─────────────────────────────────────────────────────────────────
# LLMNarrativeGenerator — metadata correctness
# ─────────────────────────────────────────────────────────────────


def test_llm_generator_records_metadata_template_path() -> None:
    """Default OFF path: generator=template in metadata."""
    tg = _mock_template_generator()
    gen = LLMNarrativeGenerator(template_generator=tg)
    spec = _make_spec()
    ctx = _make_ctx()

    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("CLINOSIM_NARRATIVE_LLM", None)
        result = gen.generate(ctx, spec)

    assert result.metadata["generator"] == "template"


def test_llm_generator_records_metadata_llm_path() -> None:
    """Opt-in path: generator=llm in metadata."""
    tg = _mock_template_generator()
    provider = _mock_provider()
    gen = LLMNarrativeGenerator(template_generator=tg, provider=provider)
    spec = _make_spec(stage2_strategy="template_seed", llm_enabled_sections=("hpi",))
    ctx = _make_ctx()

    with patch.dict("os.environ", {"CLINOSIM_NARRATIVE_LLM": "on"}):
        result = gen.generate(ctx, spec)

    assert result.metadata["generator"] == "llm"
