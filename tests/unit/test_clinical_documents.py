"""Tests for clinical document generation pipeline.

Covers:
- PromptRegistry (YAML loading + Template rendering)
- PromptCache (SHA256 disk cache)
- Provider factory (build_provider / build_from_config)
- LLMService routing with PromptRegistry + cache
- Hospital course extractor

Note: TestDocumentGeneratorE2E and TestFHIRDocumentReferenceBuilder were
removed in Task 15 (document_generator.py deleted; narrate subcommand
deprecated; _build_document_reference removed from legacy walk path).
"""

from __future__ import annotations

import pytest

from clinosim.modules.llm_service.cache import PromptCache
from clinosim.modules.llm_service.engine import (
    DOCUMENT_LOINC,
    LLMTaskType,
    document_task_loinc,
)
from clinosim.modules.llm_service.factory import build_from_config
from clinosim.modules.llm_service.prompt_registry import PromptRegistry, _stringify
from clinosim.modules.llm_service.providers import (
    BedrockProvider,
    MockProvider,
    OllamaProvider,
    build_provider,
)
from clinosim.modules.llm_service.providers.base import ProviderResponse
from clinosim.modules.output.hospital_course_extractor import (
    extract_hospital_course,
)

# ---------------------------------------------------------------------------
# PromptRegistry
# ---------------------------------------------------------------------------


class TestPromptRegistry:
    """The registry serves the narrative pipeline's prompts (the legacy
    per-document prompts were removed with LLMService.generate, Issue #2556)."""

    @pytest.mark.parametrize("task", ["narrative_seed", "narrative_seed_bundle"])
    @pytest.mark.parametrize("language", ["en", "ja"])
    def test_loads_the_narrative_prompts(self, task, language):
        spec = PromptRegistry().get(task, language)
        assert spec.system, f"{task}/{language} missing system prompt"
        assert spec.user_template, f"{task}/{language} missing user template"
        assert spec.max_tokens > 0
        assert spec.version >= 1

    def test_language_fallback_to_en(self):
        spec = PromptRegistry().get("narrative_seed", "fr")
        assert spec.system == PromptRegistry().get("narrative_seed", "en").system

    def test_render_substitutes_variables(self):
        spec = PromptRegistry().get("narrative_seed", "en")
        _, user = spec.render(
            {"section": "assessment", "severity": "moderate", "day_index": 3, "context_json_block": "{}"}
        )
        assert "assessment" in user
        assert "moderate" in user

    def test_missing_variable_raises(self):
        spec = PromptRegistry().get("narrative_seed", "en")
        with pytest.raises(KeyError):
            spec.render({"section": "assessment"})

    def test_stringify_list_as_bullets(self):
        result = _stringify(["Aspirin 81mg", "Atorvastatin 40mg"])
        assert "- Aspirin 81mg" in result
        assert "- Atorvastatin 40mg" in result

    def test_stringify_empty_list_is_none_placeholder(self):
        assert _stringify([]) == "(none)"


# ---------------------------------------------------------------------------
# PromptCache
# ---------------------------------------------------------------------------


class TestPromptCache:
    def test_roundtrip(self, tmp_path):
        cache = PromptCache(tmp_path, enabled=True)
        assert cache.get("sys", "user", "model") is None
        cache.put(
            "sys",
            "user",
            "model",
            ProviderResponse(text="hello", input_tokens=10, output_tokens=5, model="m"),
        )
        r = cache.get("sys", "user", "model")
        assert r is not None
        assert r.text == "hello"
        assert r.input_tokens == 10

    def test_cache_disabled_returns_none(self, tmp_path):
        cache = PromptCache(tmp_path, enabled=False)
        cache.put("s", "u", "m", ProviderResponse(text="x"))
        assert cache.get("s", "u", "m") is None

    def test_different_prompts_different_keys(self, tmp_path):
        cache = PromptCache(tmp_path, enabled=True)
        cache.put("s1", "u1", "m", ProviderResponse(text="a"))
        cache.put("s2", "u1", "m", ProviderResponse(text="b"))
        assert cache.get("s1", "u1", "m").text == "a"
        assert cache.get("s2", "u1", "m").text == "b"


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


class TestProviders:
    def test_mock_provider_registered(self):
        p = build_provider("mock", {})
        assert isinstance(p, MockProvider)

    def test_ollama_provider_registered(self):
        p = build_provider("ollama", {"endpoint": "http://x", "model": "m"})
        assert isinstance(p, OllamaProvider)

    def test_bedrock_provider_lazy_import(self):
        # Should not raise even without boto3 installed — lazy import
        p = build_provider("bedrock", {"region": "us-east-1"})
        assert isinstance(p, BedrockProvider)
        assert p.region == "us-east-1"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            build_provider("not-a-provider", {})

    def test_mock_complete_is_deterministic(self):
        p = MockProvider()
        r1 = p.complete("hello world", model="m")
        assert r1.text.startswith("[Mock LLM response #1]")
        r2 = p.complete("hello world", model="m")
        assert r2.text.startswith("[Mock LLM response #2]")


# ---------------------------------------------------------------------------
# LLMService — wiring
# ---------------------------------------------------------------------------


class TestLLMServiceWiring:
    def test_factory_builds_mock_service(self, tmp_path):
        cfg = {
            "judgment": {"mode": "template", "provider": ""},
            "narrative": {
                "mode": "llm",
                "provider": "mock",
                "mock": {},
                "model_map": {"small": "mock", "medium": "mock"},
                "retry_attempts": 1,
            },
            "cache": {"enabled": True, "directory": str(tmp_path / "cache")},
        }
        svc = build_from_config(cfg)
        assert svc.mode == "llm"
        assert isinstance(svc.narrative_provider, MockProvider)
        assert svc.cache is not None and svc.cache.enabled


# ---------------------------------------------------------------------------
# LOINC mapping
# ---------------------------------------------------------------------------


class TestDocumentLoinc:
    def test_tier_a_b_tasks_have_loinc(self):
        for task in [
            LLMTaskType.DISCHARGE_SUMMARY,
            LLMTaskType.DEATH_SUMMARY,
            LLMTaskType.OPERATIVE_NOTE,
            LLMTaskType.ADMISSION_HP,
            LLMTaskType.PROCEDURE_NOTE,
        ]:
            assert document_task_loinc(task), f"{task} missing LOINC"

    def test_known_loinc_codes(self):
        assert DOCUMENT_LOINC[LLMTaskType.DISCHARGE_SUMMARY] == "18842-5"
        assert DOCUMENT_LOINC[LLMTaskType.DEATH_SUMMARY] == "47046-8"  # Issue #2807
        assert DOCUMENT_LOINC[LLMTaskType.OPERATIVE_NOTE] == "11504-8"
        assert DOCUMENT_LOINC[LLMTaskType.ADMISSION_HP] == "34117-2"
        assert DOCUMENT_LOINC[LLMTaskType.PROCEDURE_NOTE] == "28570-0"


# ---------------------------------------------------------------------------
# Hospital course extractor
# ---------------------------------------------------------------------------


class TestHospitalCourseExtractor:
    def test_empty_record_still_produces_admission_discharge(self):
        record = {"encounters": [{"admission_datetime": "2026-03-01T09:00:00"}]}
        facts = extract_hospital_course(record, "en")
        assert any(f.event_type == "admission" for f in facts)

    def test_sorting_by_day(self):
        record = {
            "encounters": [
                {
                    "admission_datetime": "2026-03-01T09:00:00",
                    "discharge_datetime": "2026-03-08T10:00:00",
                    "chief_complaint": "Chest pain",
                }
            ],
            "clinical_diagnosis": {
                "admission_diagnosis_code": "I21.9",
                "admission_diagnosis_system": "icd-10-cm",
                "discharge_diagnosis_code": "I21.9",
                "discharge_diagnosis_system": "icd-10-cm",
            },
            "deceased": False,
        }
        facts = extract_hospital_course(record, "en")
        days = [f.hospital_day for f in facts]
        assert days == sorted(days)

    def test_surgery_event_only_when_surgical(self):
        # Per AD-30, CIF stores codes not names — test uses procedure_code
        # resolved via code_lookup at output time.
        record = {
            "encounters": [{"admission_datetime": "2026-03-01T09:00:00"}],
            "procedures": [
                {
                    "procedure_type": "ORIF",
                    "procedure_code": "K0463",  # resolves via k-codes.yaml
                    "category_code": "387713003",  # surgical
                    "start_datetime": "2026-03-02T10:00:00",
                    "estimated_blood_loss_ml": 300,
                },
                {
                    "procedure_type": "urinary_catheter",
                    "procedure_code": "J063",
                    "category_code": "277132007",  # therapeutic, not surgical
                    "start_datetime": "2026-03-01T12:00:00",
                },
            ],
        }
        facts = extract_hospital_course(record, "en")
        surgery = [f for f in facts if f.event_type == "surgery"]
        assert len(surgery) == 1
        # procedure_name resolved from code via k-codes.yaml ("... fixation of femoral fracture")
        assert "femoral" in surgery[0].description
