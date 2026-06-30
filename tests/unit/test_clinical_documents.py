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
    ClinicalEventData,
    DOCUMENT_LOINC,
    LLMService,
    LLMTaskType,
    PatientSummary,
    loinc_for,
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
    summarize_admission_vitals,
    summarize_discharge_medications,
    summarize_procedures,
)


# ---------------------------------------------------------------------------
# PromptRegistry
# ---------------------------------------------------------------------------


class TestPromptRegistry:
    def test_loads_all_tier_ab_prompts(self):
        reg = PromptRegistry()
        for task in [
            "discharge_summary",
            "death_summary",
            "operative_note",
            "admission_hp",
            "procedure_note",
        ]:
            spec = reg.get(task, "en")
            assert spec.system, f"{task} missing system prompt"
            assert spec.user_template, f"{task} missing user template"
            assert spec.max_tokens > 0
            assert spec.version >= 1

    def test_language_fallback_to_en(self):
        reg = PromptRegistry()
        # ja not implemented yet → falls back to en
        spec = reg.get("discharge_summary", "ja")
        assert spec.system  # en content loaded

    def test_render_substitutes_variables(self):
        reg = PromptRegistry()
        spec = reg.get("operative_note", "en")
        system, user = spec.render(
            {
                "surgery_date": "2026-03-15",
                "procedure_name": "ORIF femur",
                "procedure_code": "27236",
                "preop_diagnosis": "Right hip fracture",
                "postop_diagnosis": "Right hip fracture",
                "surgeon": "DR-SU-01",
                "assistants": ["DR-SU-02"],
                "anesthesiologist": "DR-AN-01",
                "anesthesia_type": "spinal",
                "asa_class": 3,
                "duration_minutes": 90,
                "estimated_blood_loss_ml": 300,
                "body_site": "Bone structure of femur",
                "approach": "lateral",
                "implants_used": ["compression hip screw"],
                "specimens_sent": [],
                "intraop_complications": [],
                "outcome": "Successful",
                "preop_vitals": "T 36.8°C, HR 82, BP 130/75",
                "clinical_guidance": "",
            }
        )
        assert "ORIF femur" in user
        assert "DR-SU-01" in user
        assert "system" not in system.lower() or "surgeon" in system.lower()

    def test_missing_variable_raises(self):
        reg = PromptRegistry()
        spec = reg.get("discharge_summary", "en")
        with pytest.raises(KeyError):
            spec.render({"age": 65})  # many other vars missing

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

    def test_generate_uses_prompt_registry_when_variables_given(self, tmp_path):
        svc = build_from_config(
            {
                "judgment": {"mode": "template"},
                "narrative": {
                    "mode": "llm",
                    "provider": "mock",
                    "mock": {},
                    "model_map": {"small": "mock", "medium": "mock"},
                    "retry_attempts": 1,
                },
                "cache": {"enabled": True, "directory": str(tmp_path)},
            }
        )
        variables = _discharge_summary_variables()
        ps = PatientSummary(age=68, sex="Male", country="US")
        event = ClinicalEventData(patient_summary=ps, event_data={}, language="en")

        r1 = svc.generate(LLMTaskType.DISCHARGE_SUMMARY, event, variables=variables)
        assert r1.source == "llm"
        assert r1.text
        assert r1.prompt_version == 1

        # Second call → cache hit
        r2 = svc.generate(LLMTaskType.DISCHARGE_SUMMARY, event, variables=variables)
        assert r2.source == "cache"
        assert r2.cache_hit is True
        assert r2.text == r1.text


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
            assert loinc_for(task), f"{task} missing LOINC"

    def test_known_loinc_codes(self):
        assert DOCUMENT_LOINC[LLMTaskType.DISCHARGE_SUMMARY] == "18842-5"
        assert DOCUMENT_LOINC[LLMTaskType.DEATH_SUMMARY] == "69730-0"
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
            "encounters": [
                {"admission_datetime": "2026-03-01T09:00:00"}
            ],
            "procedures": [
                {
                    "procedure_type": "ORIF",
                    "procedure_code": "K0461",   # resolves via k-codes.yaml
                    "category_code": "387713003",  # surgical
                    "start_datetime": "2026-03-02T10:00:00",
                    "estimated_blood_loss_ml": 300,
                },
                {
                    "procedure_type": "urinary_catheter",
                    "procedure_code": "D002",
                    "category_code": "277132007",  # therapeutic, not surgical
                    "start_datetime": "2026-03-01T12:00:00",
                },
            ],
        }
        facts = extract_hospital_course(record, "en")
        surgery = [f for f in facts if f.event_type == "surgery"]
        assert len(surgery) == 1
        # procedure_name resolved from code via k-codes.yaml ("Open treatment of femoral fracture...")
        assert "Open treatment" in surgery[0].description or "femoral" in surgery[0].description



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _discharge_summary_variables() -> dict:
    return {
        "age": 68,
        "sex": "Male",
        "admission_date": "2026-03-01",
        "discharge_date": "2026-03-08",
        "los_days": 7,
        "disposition": "home",
        "attending_physician": "Dr. Smith",
        "chief_complaint": "Fever and cough",
        "past_medical_history": ["Hypertension"],
        "admission_diagnosis": "Bacterial pneumonia",
        "discharge_diagnoses": ["Bacterial pneumonia (resolved)"],
        "hospital_course_bullets": ["Day 0: admitted", "Day 7: discharged"],
        "procedures_performed": "(none)",
        "discharge_medications": ["Amoxicillin 500mg PO BID x 7 days"],
        "lab_trends_summary": ["CRP: 5.2mg/L (day 0) → 180mg/L (day 2) → 12mg/L (day 7) [improving]"],
        "treatment_timeline": ["Day 0: Started Ceftriaxone IV", "Day 5: Switched to Amoxicillin PO"],
        "clinical_guidance": "",
    }
