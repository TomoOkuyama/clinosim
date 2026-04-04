"""Unit tests for LLM service."""

import pytest

from clinosim.modules.llm_service.engine import (
    ClinicalEventData,
    LLMService,
    LLMTaskType,
    PatientSummary,
)
from clinosim.modules.llm_service.providers import MockProvider


@pytest.fixture
def patient_summary():
    return PatientSummary(
        age=72, sex="F", country="JP",
        chief_complaint="Fever, cough",
        relevant_conditions=["Hypertension", "Diabetes"],
        current_diagnosis="Bacterial pneumonia",
        diagnosis_confidence=0.85,
        hospital_day=3,
        department="internal_medicine",
    )


@pytest.fixture
def event_data(patient_summary):
    return ClinicalEventData(
        patient_summary=patient_summary,
        event_data={"vitals": {"temperature": "37.5"}, "key_labs": {"CRP": "45"}},
        language="ja",
    )


@pytest.mark.unit
class TestLLMServiceModes:
    def test_none_mode(self, event_data):
        llm = LLMService(mode="none")
        response = llm.generate(LLMTaskType.PROGRESS_NOTE, event_data)
        assert response.text is None
        assert response.source == "none"

    def test_template_mode_ja(self, event_data):
        llm = LLMService(mode="template")
        response = llm.generate(LLMTaskType.PROGRESS_NOTE, event_data)
        assert response.text is not None
        assert "経過記録" in response.text  # Japanese template
        assert response.source == "template"

    def test_template_mode_en(self, patient_summary):
        llm = LLMService(mode="template")
        event = ClinicalEventData(
            patient_summary=patient_summary,
            event_data={"vitals": {}, "key_labs": {}},
            language="en",
        )
        response = llm.generate(LLMTaskType.PROGRESS_NOTE, event)
        assert "Progress Note" in response.text

    def test_template_discharge_summary(self, event_data):
        llm = LLMService(mode="template")
        event_data.event_data = {"los_days": 14, "final_diagnosis": "Pneumonia"}
        response = llm.generate(LLMTaskType.DISCHARGE_SUMMARY, event_data)
        assert response.text is not None
        assert "退院" in response.text

    def test_judgment_always_english(self, event_data):
        llm = LLMService(mode="template")
        event_data.language = "ja"
        response = llm.generate(LLMTaskType.DIAGNOSTIC_REASONING, event_data)
        # JUDGMENT tasks use English even when language is ja
        assert response.source == "template"
        assert response.text is not None


@pytest.mark.unit
class TestLLMMode:
    def test_mock_provider(self, event_data):
        mock = MockProvider()
        llm = LLMService(
            mode="llm",
            narrative_provider=mock,
            narrative_model_map={"medium": "mock-model"},
        )
        response = llm.generate(LLMTaskType.PROGRESS_NOTE, event_data)
        assert response.source == "llm"
        assert mock.call_count == 1

    def test_fallback_on_no_provider(self, event_data):
        llm = LLMService(mode="llm")  # no provider configured
        response = llm.generate(LLMTaskType.PROGRESS_NOTE, event_data)
        assert response.source == "template"  # falls back
        assert llm.fallback_count == 1

    def test_cost_report(self, event_data):
        mock = MockProvider()
        llm = LLMService(mode="llm", narrative_provider=mock,
                          narrative_model_map={"medium": "m"})
        llm.generate(LLMTaskType.PROGRESS_NOTE, event_data)
        llm.generate(LLMTaskType.DISCHARGE_SUMMARY, event_data)
        report = llm.cost_report()
        assert report["total_calls"] == 2
        assert report["total_input_tokens"] > 0
