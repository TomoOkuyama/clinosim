"""N-3 tests: narrative_seed prompt YAML ownership (PromptRegistry).

The inline _build_seed_prompt is deleted; replacement_strategy renders
prompts/{en,ja}/narrative_seed.yaml via LLMService.prompt_registry.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.replacement_strategy import (
    apply_replacement_strategy,
)
from clinosim.modules.llm_service.engine import LLMService, LLMTaskType
from clinosim.modules.llm_service.prompt_registry import PromptRegistry
from clinosim.modules.llm_service.providers import MockProvider
from clinosim.types.document import (
    DocumentType,
    DocumentTypeSpec,
    FormatType,
    NarrativeContext,
    NarrativeOutput,
)


def _make_spec() -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key="admission_hp",
        loinc_code="34117-2",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp", "us"),
        generation_frequency="admission_once",
        composition_sections=("hpi",),
        stage2_strategy="template_seed",
        llm_enabled_sections=("hpi",),
    )


def _make_ctx(target_lang: str = "en") -> NarrativeContext:
    return NarrativeContext(
        patient=SimpleNamespace(age=55, sex="M", chronic_conditions=[]),
        encounter=SimpleNamespace(encounter_id="enc-test"),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=3,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ADMISSION_HP,
        target_lang=target_lang,
        locale="jp" if target_lang == "ja" else "us",
    )


def _mock_llm(provider: MockProvider) -> LLMService:
    return LLMService(
        mode="llm",
        narrative_provider=provider,
        narrative_model_map={"medium": "mock"},
        provider_name_narrative="mock",
        retry_attempts=1,
        retry_backoff_seconds=0.0,
    )


@pytest.mark.unit
@pytest.mark.parametrize("lang", ["en", "ja"])
def test_narrative_seed_prompt_yaml_exists(lang: str) -> None:
    spec = PromptRegistry().get("narrative_seed", lang)
    assert spec.task_type == "narrative_seed"
    assert spec.system.strip()
    for var in ("${section}", "${template_text}", "${severity}", "${day_index}"):
        assert var in spec.user_template, f"{lang}: missing {var}"


@pytest.mark.unit
def test_narrative_seed_ja_prompt_is_japanese_not_en_fallback() -> None:
    en = PromptRegistry().get("narrative_seed", "en")
    ja = PromptRegistry().get("narrative_seed", "ja")
    assert ja.system != en.system
    assert any(ord(c) > 0x3000 for c in ja.system)  # contains CJK text


@pytest.mark.unit
def test_replacement_strategy_renders_registry_prompt() -> None:
    provider = MockProvider()
    template_output = NarrativeOutput(
        sections={"hpi": "SEED-CONTENT-XYZ"},
        metadata={},
        facts_used=[],
    )
    apply_replacement_strategy(
        template_output,
        _make_ctx("en"),
        _make_spec(),
        _mock_llm(provider),
        task_type=LLMTaskType.ADMISSION_HP,
        language="en",
    )
    # Rendered from the YAML user_template: seed + section + severity + day
    assert "SEED-CONTENT-XYZ" in provider.last_prompt
    assert "hpi" in provider.last_prompt
    assert "moderate" in provider.last_prompt
    assert "3" in provider.last_prompt
    # System prompt comes from the YAML (static — prompt-cache friendly)
    expected_system, _ = (
        PromptRegistry()
        .get("narrative_seed", "en")
        .render({"section": "hpi", "template_text": "x", "severity": "s", "day_index": 0})
    )
    assert provider.last_system_prompt == expected_system


@pytest.mark.unit
def test_replacement_strategy_uses_ja_prompt_for_ja() -> None:
    provider = MockProvider()
    template_output = NarrativeOutput(
        sections={"hpi": "シード本文"},
        metadata={},
        facts_used=[],
    )
    apply_replacement_strategy(
        template_output,
        _make_ctx("ja"),
        _make_spec(),
        _mock_llm(provider),
        task_type=LLMTaskType.ADMISSION_HP,
        language="ja",
    )
    ja_system = PromptRegistry().get("narrative_seed", "ja").system
    assert provider.last_system_prompt.strip() == ja_system.strip()
    assert "シード本文" in provider.last_prompt


@pytest.mark.unit
def test_inline_build_seed_prompt_deleted() -> None:
    import clinosim.modules.document.narrative.replacement_strategy as mod

    assert not hasattr(mod, "_build_seed_prompt")
