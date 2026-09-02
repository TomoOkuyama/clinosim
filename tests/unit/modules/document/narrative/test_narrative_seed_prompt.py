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
    # v3 (2026-09-02 prompt double-check): the retired variable is
    # `${template_text}` — do NOT re-add it. Passing template output to
    # the LLM as a rewrite seed anchored JA generation to EN-drift
    # template phrasing. The per-section fallback now takes the same
    # `${context_json_block}` structured-CIF payload the bundle prompt
    # uses; the LLM generates fresh from context, not from template.
    for var in ("${section}", "${context_json_block}", "${severity}", "${day_index}"):
        assert var in spec.user_template, f"{lang}: missing {var}"
    assert "${template_text}" not in spec.user_template, (
        f"{lang}: `${{template_text}}` was retired in v3 — re-adding it would leak "
        "template output as an LLM anchor (see narrative_seed.yaml v3 description)."
    )


@pytest.mark.unit
def test_narrative_seed_ja_prompt_is_japanese_not_en_fallback() -> None:
    en = PromptRegistry().get("narrative_seed", "en")
    ja = PromptRegistry().get("narrative_seed", "ja")
    assert ja.system != en.system
    assert any(ord(c) > 0x3000 for c in ja.system)  # contains CJK text


@pytest.mark.unit
def test_replacement_strategy_renders_registry_prompt() -> None:
    """v3 (2026-09-02): the LLM prompt is context-driven — the
    section-under-generation's template text does NOT leak into the
    prompt. The rendered user prompt DOES include the section name +
    severity + day + the structured `context_sections` block.
    """
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
    # v3: the LLM-enabled section's template text MUST NOT reach the LLM
    # prompt (was included via `${template_text}` in v2; retired to prevent
    # template-language-drift anchoring — see narrative_seed.yaml v3 header).
    assert "SEED-CONTENT-XYZ" not in provider.last_prompt
    # Rendered from the YAML user_template: section name + severity + day
    # + a "Context sections" header block from the context payload.
    assert "hpi" in provider.last_prompt
    assert "moderate" in provider.last_prompt
    assert "3" in provider.last_prompt
    assert "Context sections" in provider.last_prompt
    # System prompt comes from the YAML (static — prompt-cache friendly)
    expected_system, _ = (
        PromptRegistry()
        .get("narrative_seed", "en")
        .render({"section": "hpi", "context_json_block": "x", "severity": "s", "day_index": 0})
    )
    assert provider.last_system_prompt == expected_system


@pytest.mark.unit
def test_replacement_strategy_uses_ja_prompt_for_ja() -> None:
    """v3 (2026-09-02): the JA prompt is still selected on JA locale, and
    the LLM-enabled section's template text does not leak. Sibling non-LLM
    sections DO pass through as reference `context_sections` — provide one
    to prove the JA prompt sees the JA context payload.
    """
    provider = MockProvider()
    template_output = NarrativeOutput(
        sections={
            "hpi": "hpi シード本文",  # llm-enabled — this MUST NOT leak
            "assessment_and_plan": "評価・計画テンプレート本文",  # sibling — DOES pass as context
        },
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
    # LLM-enabled section's template text (retired seed) must NOT appear.
    assert "hpi シード本文" not in provider.last_prompt
    # Sibling non-LLM section's text passes through as reference context.
    assert "評価・計画テンプレート本文" in provider.last_prompt


@pytest.mark.unit
def test_inline_build_seed_prompt_deleted() -> None:
    import clinosim.modules.document.narrative.replacement_strategy as mod

    assert not hasattr(mod, "_build_seed_prompt")
