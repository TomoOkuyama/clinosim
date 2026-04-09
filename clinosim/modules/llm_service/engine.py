"""LLM Service — v0.1-beta: template mode + Ollama provider skeleton.

All LLM calls from all modules go through this service (AD-11).
JUDGMENT and NARRATIVE use independently configurable providers (AD-24).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class LLMTaskType(str, Enum):
    """
    Narrative document types for clinical data.
    Only the 5 required types per LOINC specification.
    """
    ADMISSION_HP = "admission_hp"          # LOINC 34117-2 (all admissions)
    DISCHARGE_SUMMARY = "discharge_summary"  # LOINC 18842-5 (all discharges)
    OPERATIVE_NOTE = "operative_note"      # LOINC 11504-8 (surgeries)
    PROCEDURE_NOTE = "procedure_note"      # LOINC 28570-0 (invasive bedside)
    DEATH_NOTE = "death_note"              # LOINC 69730-0 (death discharges)


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


@dataclass
class ProviderResponse:
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class OllamaProvider:
    """Local Ollama LLM provider."""

    def __init__(self, endpoint: str = "http://localhost:11434", model: str = "qwen:7b"):
        self.endpoint = endpoint
        self.default_model = model

    def complete(self, prompt: str, model: str = "", max_tokens: int = 1500,
                 system_prompt: str = "") -> ProviderResponse:
        import httpx
        model = model or self.default_model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = httpx.post(
            f"{self.endpoint}/api/chat",
            json={"model": model, "messages": messages, "stream": False,
                  "options": {"num_predict": max_tokens}},
            timeout=120,
        )
        data = resp.json()
        text = data.get("message", {}).get("content", "")
        return ProviderResponse(
            text=text,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            model=model,
        )


class LLMService:
    """
    Central LLM service for narrative document generation.

    Supports 5 document types (LOINC codes):
    - 34117-2: Admission H&P (all admissions)
    - 18842-5: Discharge Summary (all discharges)
    - 11504-8: Operative Note (surgeries)
    - 28570-0: Procedure Note (invasive bedside procedures)
    - 69730-0: Death Note (death discharges)
    """

    def __init__(self, mode: str = "none",
                 narrative_provider: Any = None,
                 narrative_model_map: dict[str, str] | None = None):
        self.mode = mode  # "none" | "template" | "llm"
        self.narrative_provider = narrative_provider
        self.narrative_model_map = narrative_model_map or {}
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.call_count = 0
        self.fallback_count = 0

    def generate(self, task_type: LLMTaskType, event: ClinicalEventData) -> LLMResponse:
        """Single entry point for all LLM interactions."""
        if self.mode == "none":
            return LLMResponse(source="none")

        language = event.language

        if self.mode == "template":
            return self._template_generate(task_type, event, language)

        # LLM mode
        return self._llm_generate(task_type, event, language)

    def _template_generate(
        self, task_type: LLMTaskType, event: ClinicalEventData, language: str
    ) -> LLMResponse:
        """Rule-based template generation. No LLM call."""
        ps = event.patient_summary
        ed = event.event_data

        match task_type:
            case LLMTaskType.ADMISSION_HP:
                text = _admission_hp(ps, ed, language)

            case LLMTaskType.DISCHARGE_SUMMARY:
                text = _discharge_summary(ps, ed, language)

            case LLMTaskType.OPERATIVE_NOTE:
                text = _operative_note(ps, ed, language)

            case LLMTaskType.PROCEDURE_NOTE:
                text = _procedure_note(ps, ed, language)

            case LLMTaskType.DEATH_NOTE:
                text = _death_note(ps, ed, language)

            case _:
                text = f"[Template: {task_type.value}]"

        return LLMResponse(text=text, source="template")


    def _llm_generate(
        self, task_type: LLMTaskType, event: ClinicalEventData,
        language: str,
    ) -> LLMResponse:
        """Call actual LLM provider. Falls back to template on failure."""
        # Use narrative provider (all tasks are narrative now)
        provider = self.narrative_provider
        model_map = self.narrative_model_map

        if provider is None:
            # No provider configured — fall back to template
            self.fallback_count += 1
            return self._template_generate(task_type, event, language)

        # Build prompt
        system_prompt, user_prompt = _build_prompt(task_type, event, language)
        model = model_map.get("medium", model_map.get("small", ""))

        # Determine max_tokens by document type
        max_tokens_map = {
            LLMTaskType.ADMISSION_HP: 3000,
            LLMTaskType.DISCHARGE_SUMMARY: 4000,
            LLMTaskType.OPERATIVE_NOTE: 2500,
            LLMTaskType.PROCEDURE_NOTE: 1500,
            LLMTaskType.DEATH_NOTE: 1000,
        }
        max_tokens = max_tokens_map.get(task_type, 2000)

        # Call with retry
        for attempt in range(3):
            try:
                response = provider.complete(
                    prompt=user_prompt,
                    model=model,
                    max_tokens=max_tokens,
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
            except Exception:
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

        case LLMTaskType.OPERATIVE_NOTE:
            system = (
                f"You are a surgeon writing a complete operative note (LOINC 11504-8). "
                f"Include: preop diagnosis, postop diagnosis, procedure performed, "
                f"indications, findings, technique, specimens, EBL, complications, "
                f"condition at end. {lang_instruction}"
            )
            procedure_type = ed.get("procedure_type", "ORIF")
            anesthesia = ed.get("anesthesia_type", "general")
            duration = ed.get("duration_minutes", 90)
            ebl = ed.get("estimated_blood_loss_ml", 300)
            findings = ed.get("findings", "")
            complications = ed.get("intraop_complications", [])
            user = (
                f"Patient: {ps.age}yo {ps.sex}\n"
                f"Preop Dx: {ed.get('preop_diagnosis', ps.current_diagnosis)}\n"
                f"Procedure: {procedure_type}\n"
                f"Anesthesia: {anesthesia}\n"
                f"Duration: {duration} min\n"
                f"EBL: {ebl} mL\n"
                f"Findings: {findings}\n"
                f"Complications: {', '.join(complications) if complications else 'None'}\n"
                f"Write the operative note."
            )

        case LLMTaskType.PROCEDURE_NOTE:
            system = (
                f"You are a physician writing a procedure note (LOINC 28570-0) "
                f"for an invasive bedside procedure. Include: indication, consent, "
                f"technique, findings, specimens, complications, patient toleration. "
                f"{lang_instruction}"
            )
            procedure_type = ed.get("procedure_type", "central_line")
            indication = ed.get("indication", ps.current_diagnosis)
            user = (
                f"Patient: {ps.age}yo {ps.sex}\n"
                f"Procedure: {procedure_type}\n"
                f"Indication: {indication}\n"
                f"Write the procedure note."
            )

        case LLMTaskType.DEATH_NOTE:
            system = (
                f"You are a physician writing a death note (LOINC 69730-0). "
                f"Include: time of death, cause of death, family notification, "
                f"autopsy discussion, belongings. Be respectful and concise. "
                f"{lang_instruction}"
            )
            death_time = ed.get("death_datetime", "")
            cause = ed.get("cause_of_death", ps.current_diagnosis)
            user = (
                f"Patient: {ps.age}yo {ps.sex}\n"
                f"Time of death: {death_time}\n"
                f"Cause: {cause}\n"
                f"Write the death note."
            )

        case _:
            system = f"You are a medical professional. {lang_instruction}"
            user = f"Task: {task_type.value}. Patient: {ps.age}yo {ps.sex}."

    return system, user


# ============================================================
# Template generators (5 required document types only)
# ============================================================

def _admission_hp(ps: PatientSummary, ed: dict, language: str) -> str:
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


def _discharge_summary(ps: PatientSummary, ed: dict, language: str) -> str:
    """Template for discharge summary (LOINC 18842-5)."""
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
    """Template for admission H&P (LOINC 34117-2)."""
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


def _operative_note(ps: PatientSummary, ed: dict, language: str) -> str:
    """Template for operative note (LOINC 11504-8)."""
    procedure_type = ed.get("procedure_type", "ORIF")
    anesthesia = ed.get("anesthesia_type", "general")
    duration = ed.get("duration_minutes", 90)
    ebl = ed.get("estimated_blood_loss_ml", 300)
    preop_dx = ed.get("preop_diagnosis", ps.current_diagnosis)
    postop_dx = ed.get("postop_diagnosis", ps.current_diagnosis)
    complications = ed.get("intraop_complications", [])

    if language == "ja":
        comp_str = "、".join(complications) if complications else "なし"
        return (
            f"【手術記録】\n"
            f"患者: {ps.age}歳 {ps.sex}\n"
            f"術前診断: {preop_dx}\n"
            f"術後診断: {postop_dx}\n"
            f"手術名: {procedure_type}\n"
            f"麻酔: {anesthesia}\n"
            f"手術時間: {duration}分\n"
            f"出血量: {ebl}mL\n"
            f"術中合併症: {comp_str}\n"
            f"術中所見: 特記事項なし。\n"
            f"終了時状態: 安定。"
        )
    else:
        comp_str = ", ".join(complications) if complications else "None"
        return (
            f"Operative Note\n"
            f"Patient: {ps.age}yo {ps.sex}\n"
            f"Preop Dx: {preop_dx}\n"
            f"Postop Dx: {postop_dx}\n"
            f"Procedure: {procedure_type}\n"
            f"Anesthesia: {anesthesia}\n"
            f"Duration: {duration} min\n"
            f"EBL: {ebl} mL\n"
            f"Complications: {comp_str}\n"
            f"Findings: Unremarkable.\n"
            f"Condition: Stable at end."
        )


def _procedure_note(ps: PatientSummary, ed: dict, language: str) -> str:
    """Template for procedure note (LOINC 28570-0) - invasive bedside."""
    procedure_type = ed.get("procedure_type", "central_line")
    indication = ed.get("indication", ps.current_diagnosis)
    complications = ed.get("complications", [])

    if language == "ja":
        comp_str = "、".join(complications) if complications else "なし"
        return (
            f"【処置記録】\n"
            f"患者: {ps.age}歳 {ps.sex}\n"
            f"処置名: {procedure_type}\n"
            f"適応: {indication}\n"
            f"手技: 清潔操作下に施行。\n"
            f"合併症: {comp_str}\n"
            f"患者状態: 良好に耐容。"
        )
    else:
        comp_str = ", ".join(complications) if complications else "None"
        return (
            f"Procedure Note\n"
            f"Patient: {ps.age}yo {ps.sex}\n"
            f"Procedure: {procedure_type}\n"
            f"Indication: {indication}\n"
            f"Technique: Performed under sterile conditions.\n"
            f"Complications: {comp_str}\n"
            f"Toleration: Patient tolerated well."
        )


def _death_note(ps: PatientSummary, ed: dict, language: str) -> str:
    """Template for death note (LOINC 69730-0)."""
    death_time = ed.get("death_datetime", "不明")
    cause = ed.get("cause_of_death", ps.current_diagnosis)

    if language == "ja":
        return (
            f"【死亡診断書】\n"
            f"患者: {ps.age}歳 {ps.sex}\n"
            f"死亡日時: {death_time}\n"
            f"死因: {cause}\n"
            f"経過: 治療に反応せず、多臓器不全が進行。\n"
            f"家族への説明: 実施済み。\n"
            f"剖検: 家族が希望せず。"
        )
    else:
        return (
            f"Death Note\n"
            f"Patient: {ps.age}yo {ps.sex}\n"
            f"Time of death: {death_time}\n"
            f"Cause of death: {cause}\n"
            f"Course: Progressive multiorgan failure despite treatment.\n"
            f"Family notification: Completed.\n"
            f"Autopsy: Declined by family."
        )


