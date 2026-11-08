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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim.datafiles import load_data_yaml, load_validated_yaml

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
    DEATH_SUMMARY = "death_summary"  # LOINC 47046-8 Summary of Death Note (Issue #2807)
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


class _TaskCategoriesFile(BaseModel):
    """Shape of ``task_categories.yaml``: each task type's dispatch category
    (configuration spec; coverage of every task type is checked below)."""

    model_config = ConfigDict(extra="forbid")
    categories: dict[str, LLMTaskCategory] = Field(min_length=1)


class _TaskLoincsFile(BaseModel):
    """Shape of ``task_loincs.yaml``: the LOINC of each template-only task."""

    model_config = ConfigDict(extra="forbid")
    loincs: dict[str, str]

    @field_validator("loincs")
    @classmethod
    def _registered(cls, loincs: dict[str, str]) -> dict[str, str]:
        from clinosim.codes import lookup

        unknown = sorted(code for code in loincs.values() if lookup("loinc", code, "en") in ("", code))
        if unknown:
            raise ValueError(f"LOINC codes not in clinosim/codes/data/loinc.yaml: {unknown}")
        return loincs


@cache
def _task_categories_raw() -> dict[str, str]:
    path = Path(__file__).resolve().parent / "reference_data" / "task_categories.yaml"
    data = load_validated_yaml(path, _TaskCategoriesFile)
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
    data = load_validated_yaml(path, _TaskLoincsFile)
    return {str(k): str(v) for k, v in (data.get("loincs", {}) or {}).items()}


def _document_loinc_from_yaml() -> dict[LLMTaskType, str]:
    """Each document type's code from document_type_specs.yaml (its one
    definition, Issue #2344), plus the template-only tasks of task_loincs.yaml."""
    # Read the data file directly: the document package imports this module.
    specs_path = Path(__file__).resolve().parents[1] / "document" / "reference_data" / "document_type_specs.yaml"
    specs = (load_data_yaml(specs_path) or {}).get("specs") or {}
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
class LLMResponse:
    """What modules get back."""

    text: str | None = None
    source: str = "none"  # "llm" | "cache"
    model: str | None = None
    provider: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit: bool = False
    # Provider-side generation stop reason: "stop" (EOS), "length"
    # (max_tokens hit — truncated), "content_filter", ... Forwarded from
    # ProviderResponse.metadata["finish_reason"] so callers can detect
    # truncation and retry with an expanded budget (see the length-retry
    # path in replacement_strategy._apply_template_seed_bundle_strategy).
    finish_reason: str | None = None


class LLMService:
    """Central LLM service. Modules reach the LLM only through ``complete_prompt`` (AD-11)."""

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
