"""LLM Service — v0.1-beta: template mode + pluggable providers.

All LLM calls from all modules go through this service (AD-11).
JUDGMENT and NARRATIVE use independently configurable providers (AD-24).

Provider implementations live in `providers/` and are instantiated via
`providers.build_provider()` or the config-driven `factory.build_from_config()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Re-export ProviderResponse from the new providers subpackage so existing
# imports keep working. New code should import from .providers directly.
from .providers import ProviderResponse  # noqa: F401
from .providers.ollama import OllamaProvider  # noqa: F401  (back-compat)


class LLMCompletionError(RuntimeError):
    """Raised by ``LLMService.complete_prompt`` when no provider is configured
    or all retry attempts are exhausted.

    This API intentionally has NO template fallback — the caller (e.g.
    ``LLMNarrativeGenerator``) owns the fallback decision (N-2, N-chain).
    """


class LLMTaskCategory(StrEnum):
    JUDGMENT = "judgment"
    NARRATIVE = "narrative"


class LLMTaskType(StrEnum):
    # JUDGMENT (always English)
    DIAGNOSTIC_REASONING = "diagnostic_reasoning"
    TREATMENT_DECISION = "treatment_decision"
    CLINICAL_JUDGMENT = "clinical_judgment"
    CONSISTENCY_REVIEW = "consistency_review"
    # NARRATIVE — clinical documents (produce FHIR DocumentReference /
    # Composition). N-3 (N-chain): kept in sync with
    # clinosim.types.document.DocumentType — every DocumentType value MUST
    # exist here as a NARRATIVE task (validated at import, see
    # _validate_document_task_sync). LLMTaskType-only extras (death_summary,
    # operative_note, procedure_note, chief_complaint) are reserved for
    # future document phases.
    CHIEF_COMPLAINT = "chief_complaint"
    ADMISSION_HP = "admission_hp"  # LOINC 34117-2
    PROGRESS_NOTE = "progress_note"  # LOINC 11506-3
    DISCHARGE_SUMMARY = "discharge_summary"  # LOINC 18842-5
    DEATH_SUMMARY = "death_summary"  # LOINC 69730-0
    OPERATIVE_NOTE = "operative_note"  # LOINC 11504-8
    PROCEDURE_NOTE = "procedure_note"  # LOINC 28570-0
    # α-min-2/3 document types (N-3 enum sync; coarse NURSING_NOTE removed)
    ADMISSION_NURSING_ASSESSMENT = "admission_nursing_assessment"  # LOINC 78390-2
    NURSING_SHIFT_NOTE = "nursing_shift_note"  # LOINC 34746-8
    NURSING_DISCHARGE_SUMMARY = "nursing_discharge_summary"  # LOINC 34745-0
    OUTPATIENT_SOAP = "outpatient_soap"  # LOINC 34131-3
    ED_NOTE = "ed_note"  # LOINC 34878-9
    ED_TRIAGE_NOTE = "ed_triage_note"  # LOINC 54094-8
    # chain 2 (厚労省4帳票, N-3 enum sync)
    ADMISSION_CARE_PLAN = "admission_care_plan"  # LOINC 18776-5
    NUTRITION_CARE_PLAN = "nutrition_care_plan"  # LOINC 80791-7
    REHABILITATION_PLAN = "rehabilitation_plan"  # LOINC 34823-5
    # P2-13 PR2b (session 47) JP-CLINS 診療情報提供書
    REFERRAL_NOTE = "referral_note"  # LOINC 57133-1
    # P2-13 PR3 (session 47) JP-eCheckup General 健診結果報告書(opt-in)
    HEALTH_CHECKUP_REPORT = "health_checkup_report"  # LOINC 53576-5


TASK_CATEGORY: dict[LLMTaskType, LLMTaskCategory] = {
    LLMTaskType.DIAGNOSTIC_REASONING: LLMTaskCategory.JUDGMENT,
    LLMTaskType.TREATMENT_DECISION: LLMTaskCategory.JUDGMENT,
    LLMTaskType.CLINICAL_JUDGMENT: LLMTaskCategory.JUDGMENT,
    LLMTaskType.CONSISTENCY_REVIEW: LLMTaskCategory.JUDGMENT,
    LLMTaskType.CHIEF_COMPLAINT: LLMTaskCategory.NARRATIVE,
    LLMTaskType.ADMISSION_HP: LLMTaskCategory.NARRATIVE,
    LLMTaskType.PROGRESS_NOTE: LLMTaskCategory.NARRATIVE,
    LLMTaskType.DISCHARGE_SUMMARY: LLMTaskCategory.NARRATIVE,
    LLMTaskType.DEATH_SUMMARY: LLMTaskCategory.NARRATIVE,
    LLMTaskType.OPERATIVE_NOTE: LLMTaskCategory.NARRATIVE,
    LLMTaskType.PROCEDURE_NOTE: LLMTaskCategory.NARRATIVE,
    LLMTaskType.ADMISSION_NURSING_ASSESSMENT: LLMTaskCategory.NARRATIVE,
    LLMTaskType.NURSING_SHIFT_NOTE: LLMTaskCategory.NARRATIVE,
    LLMTaskType.NURSING_DISCHARGE_SUMMARY: LLMTaskCategory.NARRATIVE,
    LLMTaskType.OUTPATIENT_SOAP: LLMTaskCategory.NARRATIVE,
    LLMTaskType.ED_NOTE: LLMTaskCategory.NARRATIVE,
    LLMTaskType.ED_TRIAGE_NOTE: LLMTaskCategory.NARRATIVE,
    LLMTaskType.ADMISSION_CARE_PLAN: LLMTaskCategory.NARRATIVE,
    LLMTaskType.NUTRITION_CARE_PLAN: LLMTaskCategory.NARRATIVE,
    LLMTaskType.REHABILITATION_PLAN: LLMTaskCategory.NARRATIVE,
    LLMTaskType.REFERRAL_NOTE: LLMTaskCategory.NARRATIVE,
    LLMTaskType.HEALTH_CHECKUP_REPORT: LLMTaskCategory.NARRATIVE,
}


# ============================================================
# Clinical document metadata
# LOINC codes from Regenstrief LOINC Reference (https://loinc.org/)
# α-min-2 additions NLM-verified 2026-07 (Task 8); values MUST match
# clinosim/modules/document/reference_data/document_type_specs.yaml —
# pinned by tests/unit/test_llm_task_enum_sync.py.
# ============================================================

DOCUMENT_LOINC: dict[LLMTaskType, str] = {
    LLMTaskType.ADMISSION_HP: "34117-2",  # History and physical note
    LLMTaskType.PROGRESS_NOTE: "11506-3",  # Progress note
    LLMTaskType.DISCHARGE_SUMMARY: "18842-5",  # Discharge summary note
    LLMTaskType.DEATH_SUMMARY: "69730-0",  # Death note
    LLMTaskType.OPERATIVE_NOTE: "11504-8",  # Surgical operation note
    LLMTaskType.PROCEDURE_NOTE: "28570-0",  # Procedure note
    LLMTaskType.ADMISSION_NURSING_ASSESSMENT: "78390-2",  # Nursing admission evaluation note
    LLMTaskType.NURSING_SHIFT_NOTE: "34746-8",  # Nurse Note
    LLMTaskType.NURSING_DISCHARGE_SUMMARY: "34745-0",  # Nurse Discharge summary
    LLMTaskType.OUTPATIENT_SOAP: "34131-3",  # Outpatient Note
    LLMTaskType.ED_NOTE: "34878-9",  # Emergency medicine Note
    LLMTaskType.ED_TRIAGE_NOTE: "54094-8",  # Emergency department Triage note
    LLMTaskType.ADMISSION_CARE_PLAN: "18776-5",  # Plan of care note
    LLMTaskType.NUTRITION_CARE_PLAN: "80791-7",  # Nutrition and dietetics Plan of care note
    LLMTaskType.REHABILITATION_PLAN: "34823-5",  # Physical medicine and rehab Note
    LLMTaskType.REFERRAL_NOTE: "57133-1",  # Referral note (JP-CLINS 診療情報提供書)
    LLMTaskType.HEALTH_CHECKUP_REPORT: "53576-5",  # Health checkup report (JP-eCheckup 検診・健診報告書)
}


def loinc_for(task_type: LLMTaskType) -> str | None:
    """Return the LOINC code for a document-producing task type, or None."""
    return DOCUMENT_LOINC.get(task_type)


def _validate_document_task_sync(
    document_type_values: frozenset[str] | None = None,
    narrative_task_values: frozenset[str] | None = None,
) -> None:
    """Import-time canonical-constants sync (N-3, PR-90 discipline).

    Every ``clinosim.types.document.DocumentType`` value MUST exist as a
    NARRATIVE-category ``LLMTaskType`` value — otherwise the Stage 2 LLM path
    for that document type would silently fall back to template output
    (``LLMTaskType(doc_type.value)`` raising inside the generator's broad
    fallback except). Fail loud at import instead.

    The reverse direction (LLMTaskType-only values such as ``death_summary``)
    is allowed: those are reserved for future document phases.

    Parameters exist for negative testing only; production callers pass None.
    """
    from clinosim.types.document import DocumentType

    doc_values = document_type_values if document_type_values is not None else frozenset(d.value for d in DocumentType)
    narrative_values = (
        narrative_task_values
        if narrative_task_values is not None
        else frozenset(t.value for t in LLMTaskType if TASK_CATEGORY[t] == LLMTaskCategory.NARRATIVE)
    )
    missing = doc_values - narrative_values
    if missing:
        raise ImportError(
            f"DocumentType ↔ LLMTaskType drift: DocumentType value(s) "
            f"{sorted(missing)} have no NARRATIVE LLMTaskType counterpart. "
            f"Add the member(s) to LLMTaskType + TASK_CATEGORY (+ DOCUMENT_LOINC "
            f"if document-producing) in clinosim/modules/llm_service/engine.py."
        )


_validate_document_task_sync()


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
    provider: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_version: int = 0
    cache_hit: bool = False
    fallback_reason: str = ""
    chosen_option: str | None = None
    reasoning: str | None = None


class LLMService:
    """Central LLM service. All modules call generate() — never LLM directly."""

    def __init__(
        self,
        mode: str = "none",
        judgment_provider: Any = None,
        narrative_provider: Any = None,
        judgment_model_map: dict[str, str] | None = None,
        narrative_model_map: dict[str, str] | None = None,
        prompt_registry: Any = None,
        cache: Any = None,
        retry_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
        provider_name_judgment: str = "",
        provider_name_narrative: str = "",
    ):
        self.mode = mode  # "none" | "template" | "llm"
        self.judgment_provider = judgment_provider
        self.narrative_provider = narrative_provider
        self.judgment_model_map = judgment_model_map or {}
        self.narrative_model_map = narrative_model_map or {}
        self.provider_name_judgment = provider_name_judgment
        self.provider_name_narrative = provider_name_narrative
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds

        # Lazy import to avoid cycles
        if prompt_registry is None:
            from .prompt_registry import PromptRegistry

            prompt_registry = PromptRegistry()
        self.prompt_registry = prompt_registry
        self.cache = cache  # PromptCache | None

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.call_count = 0
        self.fallback_count = 0
        self.cache_hit_count = 0

    # ------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------
    @classmethod
    def from_config_file(cls, path: str | Any) -> LLMService:
        """Build an LLMService from a YAML config file.

        See ``clinosim/config/llm_service.yaml`` for the expected schema.
        """
        from .factory import build_from_config_file

        return build_from_config_file(path)

    # ------------------------------------------------------------
    # Core entry point
    # ------------------------------------------------------------
    def generate(
        self,
        task_type: LLMTaskType,
        event: ClinicalEventData,
        variables: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Single entry point for all LLM interactions.

        Args:
            task_type: task identifier (used to select prompt template)
            event: legacy event data (used by JUDGMENT/chief_complaint)
            variables: structured variables for PromptRegistry rendering.
                When provided, YAML prompt templates are used (preferred path
                for all document-producing tasks). When None, falls back to
                the legacy ``_build_prompt`` path.
        """
        if self.mode == "none":
            return LLMResponse(source="none")

        category = TASK_CATEGORY[task_type]
        language = "en" if category == LLMTaskCategory.JUDGMENT else event.language

        if self.mode == "template":
            return self._template_generate(task_type, event, language)

        # LLM mode
        return self._llm_generate(task_type, event, language, category, variables)

    def _template_generate(self, task_type: LLMTaskType, event: ClinicalEventData, language: str) -> LLMResponse:
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

            case LLMTaskType.DEATH_SUMMARY:
                text = _death_summary_template(ps, ed, language)

            case LLMTaskType.OPERATIVE_NOTE:
                text = _operative_note_template(ps, ed, language)

            case LLMTaskType.PROCEDURE_NOTE:
                text = _procedure_note_template(ps, ed, language)

            case _:
                text = f"[Template: {task_type.value}]"

        return LLMResponse(text=text, source="template")

    def _llm_generate(
        self,
        task_type: LLMTaskType,
        event: ClinicalEventData,
        language: str,
        category: LLMTaskCategory,
        variables: dict[str, Any] | None,
    ) -> LLMResponse:
        """Call actual LLM provider. Falls back to template on failure."""
        # Select provider and model
        if category == LLMTaskCategory.JUDGMENT:
            provider = self.judgment_provider
            model_map = self.judgment_model_map
            provider_name = self.provider_name_judgment
        else:
            provider = self.narrative_provider
            model_map = self.narrative_model_map
            provider_name = self.provider_name_narrative

        if provider is None:
            # No provider configured — fall back to template
            self.fallback_count += 1
            resp = self._template_generate(task_type, event, language)
            resp.fallback_reason = "no_provider_configured"
            return resp

        # Prompt construction: prefer PromptRegistry (YAML) when variables are
        # supplied, else fall back to the legacy hardcoded _build_prompt.
        prompt_version = 0
        max_tokens = 1500
        temperature = 0.4
        if variables is not None and self.prompt_registry is not None:
            try:
                spec = self.prompt_registry.get(task_type.value, language)
                system_prompt, user_prompt = spec.render(variables)
                prompt_version = spec.version
                max_tokens = spec.max_tokens
                temperature = spec.temperature
            except (FileNotFoundError, KeyError) as e:
                self.fallback_count += 1
                resp = self._template_generate(task_type, event, language)
                resp.fallback_reason = f"prompt_error:{type(e).__name__}"
                return resp
        else:
            system_prompt, user_prompt = _build_prompt(task_type, event, language)

        model = model_map.get("medium", model_map.get("small", "")) or ""

        try:
            resp = self._complete_with_retry(
                provider=provider,
                provider_name=provider_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            resp.prompt_version = prompt_version
            return resp
        except LLMCompletionError as e:
            # All retries exhausted — fall back to template
            self.fallback_count += 1
            resp = self._template_generate(task_type, event, language)
            resp.fallback_reason = f"provider_error:{e}"[:200]
            return resp

    # ------------------------------------------------------------
    # Raw pre-built-prompt path (N-2, N-chain)
    # ------------------------------------------------------------
    def complete_prompt(
        self,
        system: str,
        user: str,
        *,
        language: str,
        task_type: LLMTaskType,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Execute a pre-built (system, user) prompt with retry + PromptCache
        + token accounting — and NO template fallback.

        This is the single low-level public API for callers that build their
        own prompts (e.g. the narrative ``apply_replacement_strategy``, which
        renders ``prompts/<lang>/narrative_seed.yaml``). Provider selection
        follows ``TASK_CATEGORY[task_type]`` (judgment vs narrative), the
        model comes from the corresponding model map.

        Error contract: raises ``LLMCompletionError`` when no provider is
        configured for the task category OR all ``retry_attempts`` are
        exhausted. The caller owns the fallback decision (AD-11 keeps the
        transport concerns — retry, disk PromptCache, cost accounting — in
        this service; content-level fallback stays with the caller).

        ``language`` is informational today (prompt text is already built);
        it is part of the signature for future per-language model routing.
        """
        del language  # reserved for per-language model routing
        if TASK_CATEGORY[task_type] == LLMTaskCategory.JUDGMENT:
            provider = self.judgment_provider
            model_map = self.judgment_model_map
            provider_name = self.provider_name_judgment
        else:
            provider = self.narrative_provider
            model_map = self.narrative_model_map
            provider_name = self.provider_name_narrative

        if provider is None:
            raise LLMCompletionError(
                f"no provider configured for task_type={task_type.value!r} (category={TASK_CATEGORY[task_type].value})"
            )

        model = model_map.get("medium", model_map.get("small", "")) or ""
        return self._complete_with_retry(
            provider=provider,
            provider_name=provider_name,
            system_prompt=system,
            user_prompt=user,
            model=model,
            max_tokens=max_tokens if max_tokens is not None else 1500,
            temperature=temperature if temperature is not None else 0.4,
        )

    def _complete_with_retry(
        self,
        provider: Any,
        provider_name: str,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Shared transport core: PromptCache lookup → provider retry loop →
        token accounting → PromptCache store.

        Raises ``LLMCompletionError`` on retry exhaustion (callers decide the
        fallback: ``_llm_generate`` falls back to template, ``complete_prompt``
        propagates).
        """
        # Cache lookup (layer 2: prompt-hash-keyed disk cache — see PromptCache)
        if self.cache is not None:
            cached = self.cache.get(system_prompt, user_prompt, model)
            if cached is not None:
                self.cache_hit_count += 1
                return LLMResponse(
                    text=cached.text,
                    source="cache",
                    model=cached.model,
                    provider=provider_name,
                    input_tokens=cached.input_tokens,
                    output_tokens=cached.output_tokens,
                    cache_hit=True,
                )

        last_error = ""
        for attempt in range(self.retry_attempts):
            try:
                response = provider.complete(
                    prompt=user_prompt,
                    model=model,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    temperature=temperature,
                )
                self.call_count += 1
                self.total_input_tokens += response.input_tokens
                self.total_output_tokens += response.output_tokens

                if self.cache is not None:
                    self.cache.put(system_prompt, user_prompt, model, response)

                return LLMResponse(
                    text=response.text,
                    source="llm",
                    model=response.model,
                    provider=provider_name,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                if attempt == self.retry_attempts - 1:
                    break
                import time

                time.sleep(self.retry_backoff_seconds * (attempt + 1))

        raise LLMCompletionError(last_error or "no attempts made")

    def cost_report(self) -> dict:
        return {
            "total_calls": self.call_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "fallback_count": self.fallback_count,
            "cache_hit_count": self.cache_hit_count,
            "cache_stats": self.cache.stats() if self.cache else None,
        }


def _build_prompt(task_type: LLMTaskType, event: ClinicalEventData, language: str) -> tuple[str, str]:
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
                f"You are a physician writing a daily progress note. Use SOAP format. Be concise. {lang_instruction}"
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
                f"You are a physician writing a discharge summary. Be comprehensive but concise. {lang_instruction}"
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
            system = f"You are a physician writing an admission History & Physical. {lang_instruction}"
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
    admit_dx = ed.get("admission_diagnosis", ps.current_diagnosis)
    meds = ed.get("discharge_medications", [])
    course = ed.get("hospital_course_bullets", [])
    course_str = "\n".join(f"  {b}" for b in course) if course else ""
    trends = ed.get("lab_trends_summary", [])
    trends_str = "\n".join(f"  {t}" for t in trends) if trends else ""
    procs = ed.get("procedures_performed", "")
    disposition = ed.get("disposition", "home")

    if language == "ja":
        med_str = "、".join(meds) if meds else "処方なし"
        text = (
            f"【退院時サマリー】\n"
            f"患者: {ps.age}歳 {ps.sex}\n"
            f"入院期間: {los}日間\n"
            f"入院診断: {admit_dx}\n"
            f"最終診断: {final_dx}\n"
        )
        if course_str:
            text += f"経過:\n{course_str}\n"
        if trends_str:
            text += f"検査推移:\n{trends_str}\n"
        if procs:
            text += f"実施手技: {procs}\n"
        text += f"退院時処方: {med_str}\n退院先: {disposition}\n外来フォロー: 2週間後。"
        return text
    else:
        med_str = ", ".join(meds) if meds else "None"
        text = (
            f"Discharge Summary\n"
            f"Patient: {ps.age}yo {ps.sex}\n"
            f"LOS: {los} days\n"
            f"Admission Dx: {admit_dx}\n"
            f"Final Dx: {final_dx}\n"
        )
        if course_str:
            text += f"Hospital course:\n{course_str}\n"
        if trends_str:
            text += f"Lab trends:\n{trends_str}\n"
        if procs:
            text += f"Procedures: {procs}\n"
        text += f"Discharge Rx: {med_str}\nDisposition: {disposition}\nFollow-up: 2 weeks."
        return text


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
    findings = ed.get("new_findings", [])
    return (
        f"Updated differential based on: {', '.join(findings)}. "
        f"Most likely: {ps.current_diagnosis} ({ps.diagnosis_confidence:.0%})."
    )


def _treatment_decision(ps: PatientSummary, ed: dict) -> str:
    decision = ed.get("decision", "continue")
    reason = ed.get("reason", "on_track")
    return f"Treatment decision: {decision}. Reason: {reason}."


def _death_summary_template(ps: PatientSummary, ed: dict, language: str) -> str:
    dx = ed.get("primary_diagnosis", ps.current_diagnosis)
    admit_dx = ed.get("admission_diagnosis", dx)
    los = ed.get("los_days", 0)
    death_dt = ed.get("death_datetime", "")
    complications = ed.get("complications", [])
    comp_str = ", ".join(complications) if complications else "(none documented)"
    course = ed.get("hospital_course_bullets", [])
    course_str = "\n".join(f"  {b}" for b in course) if course else "  (not available)"
    trends = ed.get("lab_trends_summary", [])
    trends_str = "\n".join(f"  {t}" for t in trends) if trends else ""
    timeline = ed.get("treatment_timeline", [])
    timeline_str = "\n".join(f"  {t}" for t in timeline) if timeline else ""
    terminal = ed.get("terminal_findings", "")

    if language == "ja":
        text = (
            f"【死亡時記録】\n"
            f"患者: {ps.age}歳 {ps.sex}\n"
            f"入院診断: {admit_dx}\n"
            f"最終診断: {dx}\n"
            f"入院日数: {los}日\n"
            f"死亡日時: {death_dt}\n"
            f"経過:\n{course_str}\n"
            f"合併症: {comp_str}\n"
        )
        if terminal:
            text += f"死亡時所見: {terminal}\n"
        text += "治療経過にもかかわらず死亡。"
        return text
    text = (
        f"Death Note\n"
        f"Patient: {ps.age}yo {ps.sex}\n"
        f"Admission Dx: {admit_dx}\n"
        f"Final Dx: {dx}\n"
        f"LOS: {los} days\n"
        f"Date/time of death: {death_dt}\n"
        f"Hospital course:\n{course_str}\n"
    )
    if trends_str:
        text += f"Lab trends:\n{trends_str}\n"
    if timeline_str:
        text += f"Treatment:\n{timeline_str}\n"
    if terminal:
        text += f"Terminal findings: {terminal}\n"
    text += f"Complications: {comp_str}\n"
    text += "Patient died despite maximal therapy."
    return text


def _operative_note_template(ps: PatientSummary, ed: dict, language: str) -> str:
    proc_name = ed.get("procedure_name", "Surgical procedure")
    proc_code = ed.get("procedure_code", "")
    surgeon = ed.get("surgeon", "")
    assistants = ed.get("assistants", [])
    assist_str = ", ".join(assistants) if isinstance(assistants, list) and assistants else "(none)"
    anesthesiologist = ed.get("anesthesiologist", "")
    anes_type = ed.get("anesthesia_type", "general")
    asa_class = ed.get("asa_class", "")
    duration = ed.get("duration_minutes", 0)
    ebl = ed.get("estimated_blood_loss_ml", 0)
    preop = ed.get("preop_diagnosis", ps.current_diagnosis)
    postop = ed.get("postop_diagnosis", preop)
    body_site = ed.get("body_site", "")
    approach = ed.get("approach", "")
    implants = ed.get("implants_used", [])
    implant_str = ", ".join(implants) if isinstance(implants, list) and implants else "(none)"
    specimens = ed.get("specimens_sent", [])
    specimen_str = ", ".join(specimens) if isinstance(specimens, list) and specimens else "(none)"
    complications = ed.get("intraop_complications", [])
    comp_str = ", ".join(complications) if isinstance(complications, list) and complications else "None"
    outcome = ed.get("outcome", "Successful")
    preop_vitals = ed.get("preop_vitals", "")

    if language == "ja":
        text = (
            f"【手術記録】\n"
            f"術式: {proc_name} ({proc_code})\n"
            f"執刀医: {surgeon}\n"
            f"助手: {assist_str}\n"
            f"麻酔科医: {anesthesiologist}\n"
            f"麻酔: {anes_type} (ASA {asa_class})\n"
            f"手術時間: {duration}分\n"
            f"出血量: {ebl}mL\n"
            f"部位: {body_site}\n"
        )
        if approach:
            text += f"アプローチ: {approach}\n"
        text += (
            f"術前診断: {preop}\n"
            f"術後診断: {postop}\n"
            f"インプラント: {implant_str}\n"
            f"検体: {specimen_str}\n"
            f"合併症: {comp_str}\n"
            f"転帰: {outcome}"
        )
        return text
    text = (
        f"Operative Note\n"
        f"Procedure: {proc_name} ({proc_code})\n"
        f"Surgeon: {surgeon}\n"
        f"Assistant(s): {assist_str}\n"
        f"Anesthesiologist: {anesthesiologist}\n"
        f"Anesthesia: {anes_type} (ASA {asa_class})\n"
        f"Duration: {duration} min\n"
        f"EBL: {ebl} mL\n"
        f"Body site: {body_site}\n"
    )
    if approach:
        text += f"Approach: {approach}\n"
    if preop_vitals:
        text += f"Preop vitals: {preop_vitals}\n"
    text += (
        f"Preop Dx: {preop}\n"
        f"Postop Dx: {postop}\n"
        f"Implants: {implant_str}\n"
        f"Specimens: {specimen_str}\n"
        f"Complications: {comp_str}\n"
        f"Outcome: {outcome}"
    )
    return text


def _procedure_note_template(ps: PatientSummary, ed: dict, language: str) -> str:
    proc_name = ed.get("procedure_name", "Bedside procedure")
    proc_code = ed.get("procedure_code", "")
    operator = ed.get("operator", "")
    indication = ed.get("indication", ps.chief_complaint)
    body_site = ed.get("body_site", "")
    anes_type = ed.get("anesthesia_type", "local")
    duration = ed.get("duration_minutes", 0)
    findings = ed.get("findings", "")
    specimens = ed.get("specimens_obtained", [])
    specimen_str = ", ".join(specimens) if isinstance(specimens, list) and specimens else "(none)"
    complications = ed.get("complications", [])
    comp_str = ", ".join(complications) if isinstance(complications, list) and complications else "None"
    outcome = ed.get("outcome", "Successful")

    if language == "ja":
        text = (
            f"【処置記録】\n"
            f"処置: {proc_name} ({proc_code})\n"
            f"実施者: {operator}\n"
            f"適応: {indication}\n"
            f"部位: {body_site}\n"
            f"麻酔: {anes_type}\n"
            f"所要時間: {duration}分\n"
        )
        if findings:
            text += f"所見: {findings}\n"
        text += f"検体: {specimen_str}\n合併症: {comp_str}\n転帰: {outcome}"
        return text
    text = (
        f"Procedure Note\n"
        f"Procedure: {proc_name} ({proc_code})\n"
        f"Operator: {operator}\n"
        f"Indication: {indication}\n"
        f"Site: {body_site}\n"
        f"Anesthesia: {anes_type}\n"
        f"Duration: {duration} min\n"
    )
    if findings:
        text += f"Findings: {findings}\n"
    text += f"Specimens: {specimen_str}\nComplications: {comp_str}\nOutcome: {outcome}"
    return text
