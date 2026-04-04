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

    def __init__(self, mode: str = "none"):
        self.mode = mode  # "none" | "template" | "llm"

    def generate(self, task_type: LLMTaskType, event: ClinicalEventData) -> LLMResponse:
        """Single entry point for all LLM interactions."""
        if self.mode == "none":
            return LLMResponse(source="none")

        category = TASK_CATEGORY[task_type]
        language = "en" if category == LLMTaskCategory.JUDGMENT else event.language

        if self.mode == "template":
            return self._template_generate(task_type, event, language)

        # LLM mode (not yet implemented — fall back to template)
        return self._template_generate(task_type, event, language)

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
