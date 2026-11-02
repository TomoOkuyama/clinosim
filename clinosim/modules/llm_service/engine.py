"""LLM Service — v0.1-beta: template mode + pluggable providers.

All LLM calls from all modules go through this service (AD-11).
JUDGMENT and NARRATIVE use independently configurable providers (AD-24).

Provider implementations live in `providers/` and are instantiated via
`providers.build_provider()` or the config-driven `factory.build_from_config()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.locale.i18n import t

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
    # P2-13 PR2b JP-CLINS 診療情報提供書
    REFERRAL_NOTE = "referral_note"  # LOINC 57133-1
    # P2-13 PR3 JP-eCheckup General 健診結果報告書(opt-in)
    HEALTH_CHECKUP_REPORT = "health_checkup_report"  # LOINC 53576-5
    # Issue #961 死亡診断書 (Death certificate; 医師法第 20 条 mandate)
    DEATH_CERTIFICATE = "death_certificate"  # LOINC 64297-5
    # Issue #961 extension 死亡退院サマリー (Death discharge summary; replaces
    # generic 退院時サマリー on deceased encounters)
    DEATH_DISCHARGE_SUMMARY = "death_discharge_summary"  # LOINC 18842-5 (specialized title)


# LLMTaskType → LLMTaskCategory dispatch classification.
# Authority yaml: `clinosim/modules/llm_service/reference_data/
# task_categories.yaml` (hardcoded-review Phase A10). The loader
# validates coverage at import time — a new LLMTaskType enum value
# without a corresponding yaml row raises ImportError.


@cache
def _task_categories_raw() -> dict[str, str]:
    path = Path(__file__).resolve().parent / "reference_data" / "task_categories.yaml"
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {str(k): str(v) for k, v in (data.get("categories", {}) or {}).items()}


def _task_category_from_yaml() -> dict[LLMTaskType, LLMTaskCategory]:
    out: dict[LLMTaskType, LLMTaskCategory] = {}
    unknown: list[str] = []
    for key, value in _task_categories_raw().items():
        try:
            task = LLMTaskType(key)
            cat = LLMTaskCategory(value)
        except ValueError:
            unknown.append(key)
            continue
        out[task] = cat
    missing = {t for t in LLMTaskType} - set(out)
    if missing or unknown:
        detail = ""
        if missing:
            detail += f" missing categories for: {sorted(t.value for t in missing)}"
        if unknown:
            detail += f" unknown task_categories keys: {sorted(unknown)}"
        raise ImportError(
            "LLMTaskCategory yaml coverage check failed:"
            + detail
            + " (edit clinosim/modules/llm_service/reference_data/task_categories.yaml)"
        )
    return out


TASK_CATEGORY: dict[LLMTaskType, LLMTaskCategory] = _task_category_from_yaml()


# ============================================================
# Clinical document metadata
# LOINC codes from Regenstrief LOINC Reference (https://loinc.org/).
# Authority yaml: `clinosim/modules/llm_service/reference_data/
# task_loincs.yaml` (hardcoded-review Phase A10). The sync test
# `tests/unit/test_llm_task_enum_sync.py::test_document_loinc_
# matches_document_type_specs_yaml` continues to enforce agreement
# with the 18 overlapping entries in `document_type_specs.yaml`;
# DEATH_SUMMARY is template-only (not in the document pipeline) and
# lives only in task_loincs.yaml.
# ============================================================


@cache
def _task_loincs_raw() -> dict[str, str]:
    path = Path(__file__).resolve().parent / "reference_data" / "task_loincs.yaml"
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {str(k): str(v) for k, v in (data.get("loincs", {}) or {}).items()}


def _document_loinc_from_yaml() -> dict[LLMTaskType, str]:
    """Each document type's code from document_type_specs.yaml (its one
    definition, Issue #2344), plus the template-only tasks of task_loincs.yaml."""
    # Read the data file directly: the document package imports this module.
    specs_path = Path(__file__).resolve().parents[1] / "document" / "reference_data" / "document_type_specs.yaml"
    with specs_path.open(encoding="utf-8") as fh:
        specs = (yaml.safe_load(fh) or {}).get("specs") or {}
    codes = {str(k): str(v["loinc_code"]) for k, v in specs.items()}
    overlap = sorted(set(codes) & set(_task_loincs_raw()))
    if overlap:
        raise ImportError(f"task_loincs.yaml redefines document types of document_type_specs.yaml: {overlap}")
    codes.update(_task_loincs_raw())
    out: dict[LLMTaskType, str] = {}
    unknown: list[str] = []
    for key, code in codes.items():
        try:
            task = LLMTaskType(key)
        except ValueError:
            unknown.append(key)
            continue
        out[task] = code
    if unknown:
        raise ImportError(
            "DOCUMENT_LOINC yaml references unknown LLMTaskType values: "
            f"{sorted(unknown)} (edit clinosim/modules/llm_service/"
            "reference_data/task_loincs.yaml)"
        )
    return out


DOCUMENT_LOINC: dict[LLMTaskType, str] = _document_loinc_from_yaml()


def document_task_loinc(task_type: LLMTaskType) -> str | None:
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
    # Provider-side generation stop reason: "stop" (EOS), "length"
    # (max_tokens hit — truncated), "content_filter", ... Forwarded from
    # ProviderResponse.metadata["finish_reason"] so callers can detect
    # truncation and retry with an expanded budget (see the length-retry
    # path in replacement_strategy._apply_template_seed_bundle_strategy).
    finish_reason: str | None = None


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
                text = _chief_complaint(ed, language)

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
                cached_finish = (cached.metadata or {}).get("finish_reason") if cached.metadata else None
                return LLMResponse(
                    text=cached.text,
                    source="cache",
                    model=cached.model,
                    provider=provider_name,
                    input_tokens=cached.input_tokens,
                    output_tokens=cached.output_tokens,
                    cache_hit=True,
                    finish_reason=cached_finish,
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

                provider_finish = (response.metadata or {}).get("finish_reason") if response.metadata else None
                return LLMResponse(
                    text=response.text,
                    source="llm",
                    model=response.model,
                    provider=provider_name,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    finish_reason=provider_finish,
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


def _output_language_instruction(language: str) -> str:
    """Output-language instruction written in the target language (Issue #2278)."""
    from clinosim.countries import output_language_instruction

    return output_language_instruction(language)


def _build_prompt(task_type: LLMTaskType, event: ClinicalEventData, language: str) -> tuple[str, str]:
    """Build system and user prompts for an LLM call. Centralized here (AD-11)."""
    ps = event.patient_summary
    ed = event.event_data

    lang_instruction = _output_language_instruction(language)

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


def _chief_complaint(ed: dict, lang: str) -> str:
    """Chief-complaint template (phrases in ``narrative_phrases.yaml``
    ``llm_template``, Issue #2399)."""
    if "symptoms" in ed:
        symptoms = t("llm_template.list_sep", lang).join(ed["symptoms"])
    else:
        symptoms = t("llm_template.default_symptoms", lang)
    return t("llm_template.chief_complaint", lang, days=ed.get("symptom_days", 3), symptoms=symptoms)


def _block(key: str, lang: str, value: Any, **params: Any) -> str:
    """An optional template line; ``""`` when ``value`` is empty."""
    return t(f"llm_template.{key}", lang, **params) if value else ""


def _joined(items: Any, lang: str, empty_key: str) -> str:
    """``items`` joined with ", "; the catalog's empty marker when there are none."""
    return ", ".join(items) if isinstance(items, list) and items else t(f"llm_template.{empty_key}", lang)


def _progress_note(ps: PatientSummary, ed: dict, language: str) -> str:
    vitals = ed.get("vitals", {})
    labs = ed.get("key_labs", {})
    return t(
        "llm_template.progress_note",
        language,
        day=ps.hospital_day,
        temp=vitals.get("temperature", "---"),
        crp=labs.get("CRP", "---"),
        dx=ps.current_diagnosis,
    )


def _discharge_summary(ps: PatientSummary, ed: dict, language: str) -> str:
    meds = ed.get("discharge_medications", [])
    course = ed.get("hospital_course_bullets", [])
    course_str = "\n".join(f"  {b}" for b in course) if course else ""
    trends = ed.get("lab_trends_summary", [])
    trends_str = "\n".join(f"  {x}" for x in trends) if trends else ""
    procs = ed.get("procedures_performed", "")
    meds_str = (
        t("llm_template.list_sep", language).join(meds) if meds else t("llm_template.no_discharge_meds", language)
    )
    return t(
        "llm_template.discharge_summary",
        language,
        age=ps.age,
        sex=ps.sex,
        los=ed.get("los_days", 14),
        admit_dx=ed.get("admission_diagnosis", ps.current_diagnosis),
        final_dx=ed.get("final_diagnosis", ps.current_diagnosis),
        course_block=_block("course_block", language, course_str, course=course_str),
        trends_block=_block("trends_block", language, trends_str, trends=trends_str),
        procs_block=_block("procs_block", language, procs, procs=procs),
        meds=meds_str,
        disposition=ed.get("disposition", "home"),
    )


def _admission_hp(ps: PatientSummary, ed: dict, language: str) -> str:
    return t(
        "llm_template.admission_hp",
        language,
        cc=ps.chief_complaint,
        age=ps.age,
        sex=ps.sex,
        conditions=", ".join(ps.relevant_conditions or []),
        dx=ps.current_diagnosis,
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
    complications = ed.get("complications", [])
    course = ed.get("hospital_course_bullets", [])
    course_str = "\n".join(f"  {b}" for b in course) if course else "  " + t("llm_template.not_available", language)
    trends = ed.get("lab_trends_summary", [])
    trends_str = "\n".join(f"  {x}" for x in trends) if trends else ""
    timeline = ed.get("treatment_timeline", [])
    timeline_str = "\n".join(f"  {x}" for x in timeline) if timeline else ""
    terminal = ed.get("terminal_findings", "")
    return t(
        "llm_template.death_summary",
        language,
        age=ps.age,
        sex=ps.sex,
        admit_dx=ed.get("admission_diagnosis", dx),
        dx=dx,
        los=ed.get("los_days", 0),
        death_dt=ed.get("death_datetime", ""),
        course=course_str,
        complications=", ".join(complications) if complications else t("llm_template.none_documented", language),
        trends_block=_block("trends_block", language, trends_str, trends=trends_str),
        timeline_block=_block("timeline_block", language, timeline_str, timeline=timeline_str),
        terminal_block=_block("terminal_block", language, terminal, terminal=terminal),
    )


def _operative_note_template(ps: PatientSummary, ed: dict, language: str) -> str:
    preop = ed.get("preop_diagnosis", ps.current_diagnosis)
    approach = ed.get("approach", "")
    preop_vitals = ed.get("preop_vitals", "")
    return t(
        "llm_template.operative_note",
        language,
        proc=ed.get("procedure_name", "Surgical procedure"),
        code=ed.get("procedure_code", ""),
        surgeon=ed.get("surgeon", ""),
        assistants=_joined(ed.get("assistants", []), language, "none_listed"),
        anesthesiologist=ed.get("anesthesiologist", ""),
        anesthesia=ed.get("anesthesia_type", "general"),
        asa=ed.get("asa_class", ""),
        duration=ed.get("duration_minutes", 0),
        ebl=ed.get("estimated_blood_loss_ml", 0),
        site=ed.get("body_site", ""),
        approach_block=_block("approach_block", language, approach, approach=approach),
        preop_vitals_block=_block("preop_vitals_block", language, preop_vitals, vitals=preop_vitals),
        preop=preop,
        postop=ed.get("postop_diagnosis", preop),
        implants=_joined(ed.get("implants_used", []), language, "none_listed"),
        specimens=_joined(ed.get("specimens_sent", []), language, "none_listed"),
        complications=_joined(ed.get("intraop_complications", []), language, "no_complications"),
        outcome=ed.get("outcome", "Successful"),
    )


def _procedure_note_template(ps: PatientSummary, ed: dict, language: str) -> str:
    findings = ed.get("findings", "")
    return t(
        "llm_template.procedure_note",
        language,
        proc=ed.get("procedure_name", "Bedside procedure"),
        code=ed.get("procedure_code", ""),
        operator=ed.get("operator", ""),
        indication=ed.get("indication", ps.chief_complaint),
        site=ed.get("body_site", ""),
        anesthesia=ed.get("anesthesia_type", "local"),
        duration=ed.get("duration_minutes", 0),
        findings_block=_block("findings_block", language, findings, findings=findings),
        specimens=_joined(ed.get("specimens_obtained", []), language, "none_listed"),
        complications=_joined(ed.get("complications", []), language, "no_complications"),
        outcome=ed.get("outcome", "Successful"),
    )
