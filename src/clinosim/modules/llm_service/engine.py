"""LLM Service — v0.1-beta: template mode + Ollama provider skeleton.

All LLM calls from all modules go through this service (AD-11).
JUDGMENT and NARRATIVE use independently configurable providers (AD-24).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class LLMTaskCategory(str, Enum):
    JUDGMENT = "judgment"
    NARRATIVE = "narrative"


class LLMTaskType(str, Enum):
    # JUDGMENT (always English)
    DIAGNOSTIC_REASONING = "diagnostic_reasoning"
    TREATMENT_DECISION = "treatment_decision"
    CLINICAL_JUDGMENT = "clinical_judgment"
    CONSISTENCY_REVIEW = "consistency_review"
    # NARRATIVE (target language)
    CHIEF_COMPLAINT = "chief_complaint"
    ADMISSION_HP = "admission_hp"
    PROGRESS_NOTE = "progress_note"
    DISCHARGE_SUMMARY = "discharge_summary"
    NURSING_NOTE = "nursing_note"


TASK_CATEGORY: dict[LLMTaskType, LLMTaskCategory] = {
    LLMTaskType.DIAGNOSTIC_REASONING: LLMTaskCategory.JUDGMENT,
    LLMTaskType.TREATMENT_DECISION: LLMTaskCategory.JUDGMENT,
    LLMTaskType.CLINICAL_JUDGMENT: LLMTaskCategory.JUDGMENT,
    LLMTaskType.CONSISTENCY_REVIEW: LLMTaskCategory.JUDGMENT,
    LLMTaskType.CHIEF_COMPLAINT: LLMTaskCategory.NARRATIVE,
    LLMTaskType.ADMISSION_HP: LLMTaskCategory.NARRATIVE,
    LLMTaskType.PROGRESS_NOTE: LLMTaskCategory.NARRATIVE,
    LLMTaskType.DISCHARGE_SUMMARY: LLMTaskCategory.NARRATIVE,
    LLMTaskType.NURSING_NOTE: LLMTaskCategory.NARRATIVE,
}


@dataclass
class PatientSummary:
    """Compact patient representation for LLM context."""
    age: int = 0
    sex: str = ""
    country: str = ""
    chief_complaint: str = ""
    relevant_conditions: list[str] | None = None
    current_diagnosis: str = ""
    diagnosis_confidence: float = 0.0
    hospital_day: int = 0
    department: str = ""


@dataclass
class ClinicalEventData:
    """What modules pass to llm_service. Modules never write prompts."""
    patient_summary: PatientSummary
    event_data: dict[str, Any]
    language: str = "ja"


@dataclass
class LLMResponse:
    """What modules get back."""
    text: str | None = None
    source: str = "none"  # "llm" | "template" | "cache" | "none"
    model: str | None = None
    chosen_option: str | None = None
    reasoning: str | None = None


class LLMService:
    """Central LLM service. All modules call generate() — never LLM directly."""

    def __init__(self, mode: str = "none", judgment_provider: Any = None,
                 narrative_provider: Any = None,
                 judgment_model_map: dict[str, str] | None = None,
                 narrative_model_map: dict[str, str] | None = None):
        self.mode = mode  # "none" | "template" | "llm"
        self.judgment_provider = judgment_provider
        self.narrative_provider = narrative_provider
        self.judgment_model_map = judgment_model_map or {}
        self.narrative_model_map = narrative_model_map or {}
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.call_count = 0
        self.fallback_count = 0

    def generate(self, task_type: LLMTaskType, event: ClinicalEventData) -> LLMResponse:
        """Single entry point for all LLM interactions."""
        if self.mode == "none":
            return LLMResponse(source="none")

        category = TASK_CATEGORY[task_type]
        language = "en" if category == LLMTaskCategory.JUDGMENT else event.language

        if self.mode == "template":
            return self._template_generate(task_type, event, language)

        # LLM mode
        return self._llm_generate(task_type, event, language, category)

    def _template_generate(
        self, task_type: LLMTaskType, event: ClinicalEventData, language: str
    ) -> LLMResponse:
        """Rule-based template generation. No LLM call."""
        ps = event.patient_summary
        ed = event.event_data

        match task_type:
            case LLMTaskType.CHIEF_COMPLAINT:
                if language == "ja":
                    text = _jp_chief_complaint(ps, ed)
                else:
                    text = _en_chief_complaint(ps, ed)

            case LLMTaskType.PROGRESS_NOTE:
                text = _progress_note(ps, ed, language)

            case LLMTaskType.DISCHARGE_SUMMARY:
                text = _discharge_summary(ps, ed, language)

            case LLMTaskType.ADMISSION_HP:
                text = _admission_hp(ps, ed, language)

            case LLMTaskType.DIAGNOSTIC_REASONING:
                text = _diagnostic_reasoning(ps, ed)

            case LLMTaskType.TREATMENT_DECISION:
                text = _treatment_decision(ps, ed)

            case _:
                text = f"[Template: {task_type.value}]"

        return LLMResponse(text=text, source="template")


    def _llm_generate(
        self, task_type: LLMTaskType, event: ClinicalEventData,
        language: str, category: LLMTaskCategory,
    ) -> LLMResponse:
        """Call actual LLM provider. Falls back to template on failure."""
        # Select provider and model
        if category == LLMTaskCategory.JUDGMENT:
            provider = self.judgment_provider
            model_map = self.judgment_model_map
        else:
            provider = self.narrative_provider
            model_map = self.narrative_model_map

        if provider is None:
            # No provider configured — fall back to template
            self.fallback_count += 1
            return self._template_generate(task_type, event, language)

        # Build prompt
        system_prompt, user_prompt = _build_prompt(task_type, event, language)
        model = model_map.get("medium", model_map.get("small", ""))

        # Call with retry
        for attempt in range(3):
            try:
                response = provider.complete(
                    prompt=user_prompt,
                    model=model,
                    max_tokens=1500,
                    system_prompt=system_prompt,
                )
                self.call_count += 1
                self.total_input_tokens += response.input_tokens
                self.total_output_tokens += response.output_tokens

                return LLMResponse(
                    text=response.text,
                    source="llm",
                    model=response.model,
                )
            except Exception as e:
                if attempt == 2:
                    # All retries exhausted — fall back to template
                    self.fallback_count += 1
                    return self._template_generate(task_type, event, language)
                import time
                time.sleep(1 * (attempt + 1))

        return self._template_generate(task_type, event, language)

    def cost_report(self) -> dict:
        return {
            "total_calls": self.call_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "fallback_count": self.fallback_count,
        }


def _build_prompt(task_type: LLMTaskType, event: ClinicalEventData,
                   language: str) -> tuple[str, str]:
    """Build system and user prompts for an LLM call. Centralized here (AD-11)."""
    ps = event.patient_summary
    ed = event.event_data

    lang_instruction = {
        "ja": "Write in Japanese. Use appropriate Japanese medical terminology.",
        "en": "Write in English. Use standard medical terminology.",
    }.get(language, "Write in English.")

    match task_type:
        case LLMTaskType.PROGRESS_NOTE:
            system = (
                f"You are a physician writing a daily progress note. "
                f"Use SOAP format. Be concise. {lang_instruction}"
            )
            user = (
                f"Patient: {ps.age}yo {ps.sex}, Hospital Day {ps.hospital_day}\n"
                f"Diagnosis: {ps.current_diagnosis}\n"
                f"Vitals: {ed.get('vitals', {})}\n"
                f"Key labs: {ed.get('key_labs', {})}\n"
                f"Write the progress note."
            )

        case LLMTaskType.DISCHARGE_SUMMARY:
            system = (
                f"You are a physician writing a discharge summary. "
                f"Be comprehensive but concise. {lang_instruction}"
            )
            user = (
                f"Patient: {ps.age}yo {ps.sex}\n"
                f"Diagnosis: {ed.get('final_diagnosis', ps.current_diagnosis)}\n"
                f"LOS: {ed.get('los_days', 14)} days\n"
                f"Key events: {ed.get('key_events', [])}\n"
                f"Discharge medications: {ed.get('discharge_medications', [])}\n"
                f"Write the discharge summary."
            )

        case LLMTaskType.ADMISSION_HP:
            system = (
                f"You are a physician writing an admission History & Physical. "
                f"{lang_instruction}"
            )
            conditions = ", ".join(ps.relevant_conditions or [])
            user = (
                f"Patient: {ps.age}yo {ps.sex}\n"
                f"Chief complaint: {ps.chief_complaint}\n"
                f"PMH: {conditions}\n"
                f"Write the admission H&P."
            )

        case LLMTaskType.CHIEF_COMPLAINT:
            system = f"Generate a brief chief complaint statement. {lang_instruction}"
            symptoms = ed.get("symptoms", ["fever", "cough"])
            days = ed.get("symptom_days", 3)
            user = f"Symptoms: {', '.join(symptoms)} for {days} days."

        case LLMTaskType.DIAGNOSTIC_REASONING:
            system = "You are a physician explaining diagnostic reasoning. Write in English."
            user = (
                f"Differential changed: {ed.get('differential_before', {})} "
                f"-> {ed.get('differential_after', {})}\n"
                f"New findings: {ed.get('new_findings', [])}\n"
                f"Explain the reasoning."
            )

        case _:
            system = f"You are a medical professional. {lang_instruction}"
            user = f"Task: {task_type.value}. Patient: {ps.age}yo {ps.sex}."

    return system, user


# ============================================================
# Template generators
# ============================================================

def _jp_chief_complaint(ps: PatientSummary, ed: dict) -> str:
    symptoms = ed.get("symptoms", ["発熱", "咳嗽", "呼吸困難"])
    days = ed.get("symptom_days", 3)
    return f"{days}日前からの{'、'.join(symptoms)}を主訴に来院。"


def _en_chief_complaint(ps: PatientSummary, ed: dict) -> str:
    symptoms = ed.get("symptoms", ["fever", "cough", "dyspnea"])
    days = ed.get("symptom_days", 3)
    return f"{days}-day history of {', '.join(symptoms)}."


def _progress_note(ps: PatientSummary, ed: dict, language: str) -> str:
    day = ps.hospital_day
    vitals = ed.get("vitals", {})
    labs = ed.get("key_labs", {})

    if language == "ja":
        t = vitals.get("temperature", "---")
        crp = labs.get("CRP", "---")
        return (
            f"【経過記録 Day {day}】\n"
            f"S: 特記事項なし。食事摂取良好。\n"
            f"O: 体温 {t}℃。CRP {crp}。\n"
            f"A: {ps.current_diagnosis}。経過良好。\n"
            f"P: 現治療継続。"
        )
    else:
        t = vitals.get("temperature", "---")
        crp = labs.get("CRP", "---")
        return (
            f"Day {day} Progress Note\n"
            f"S: No acute complaints. Tolerating diet.\n"
            f"O: Temp {t}C. CRP {crp}.\n"
            f"A: {ps.current_diagnosis}. Improving.\n"
            f"P: Continue current management."
        )


def _discharge_summary(ps: PatientSummary, ed: dict, language: str) -> str:
    los = ed.get("los_days", 14)
    final_dx = ed.get("final_diagnosis", ps.current_diagnosis)
    meds = ed.get("discharge_medications", [])

    if language == "ja":
        med_str = "、".join(meds) if meds else "処方なし"
        return (
            f"【退院時サマリー】\n"
            f"患者: {ps.age}歳 {ps.sex}\n"
            f"入院期間: {los}日間\n"
            f"最終診断: {final_dx}\n"
            f"経過: 抗菌薬治療により軽快。\n"
            f"退院時処方: {med_str}\n"
            f"外来フォロー: 2週間後。"
        )
    else:
        med_str = ", ".join(meds) if meds else "None"
        return (
            f"Discharge Summary\n"
            f"Patient: {ps.age}yo {ps.sex}\n"
            f"LOS: {los} days\n"
            f"Final Dx: {final_dx}\n"
            f"Course: Improved with antibiotic therapy.\n"
            f"Discharge Rx: {med_str}\n"
            f"Follow-up: 2 weeks."
        )


def _admission_hp(ps: PatientSummary, ed: dict, language: str) -> str:
    conditions = ", ".join(ps.relevant_conditions or [])
    if language == "ja":
        return (
            f"【入院時記録】\n"
            f"主訴: {ps.chief_complaint}\n"
            f"現病歴: {ps.age}歳{ps.sex}。既往に{conditions}あり。\n"
            f"身体所見: (記載省略)\n"
            f"アセスメント: {ps.current_diagnosis}疑い。\n"
            f"プラン: 抗菌薬治療開始。"
        )
    else:
        return (
            f"Admission H&P\n"
            f"CC: {ps.chief_complaint}\n"
            f"HPI: {ps.age}yo {ps.sex} with PMH of {conditions}.\n"
            f"PE: (deferred)\n"
            f"A: Suspected {ps.current_diagnosis}.\n"
            f"P: Initiate antibiotic therapy."
        )


def _diagnostic_reasoning(ps: PatientSummary, ed: dict) -> str:
    diff_before = ed.get("differential_before", {})
    diff_after = ed.get("differential_after", {})
    findings = ed.get("new_findings", [])
    return (
        f"Updated differential based on: {', '.join(findings)}. "
        f"Most likely: {ps.current_diagnosis} ({ps.diagnosis_confidence:.0%})."
    )


def _treatment_decision(ps: PatientSummary, ed: dict) -> str:
    decision = ed.get("decision", "continue")
    reason = ed.get("reason", "on_track")
    return f"Treatment decision: {decision}. Reason: {reason}."
