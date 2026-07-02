"""LLM service module — the single gateway for all LLM calls (AD-11, AD-24).

Public API surface (N-3, N-chain 2026-07-02). All other modules import from
this package root; provider SDKs (Ollama / Bedrock / Anthropic) are never
called directly by any other module.
"""

from clinosim.modules.llm_service.cache import PromptCache
from clinosim.modules.llm_service.engine import (
    DOCUMENT_LOINC,
    TASK_CATEGORY,
    ClinicalEventData,
    LLMCompletionError,
    LLMResponse,
    LLMService,
    LLMTaskCategory,
    LLMTaskType,
    PatientSummary,
    loinc_for,
)
from clinosim.modules.llm_service.factory import build_from_config, build_from_config_file
from clinosim.modules.llm_service.prompt_registry import PromptRegistry, PromptSpec
from clinosim.modules.llm_service.providers import (
    LLMProvider,
    MockProvider,
    ProviderResponse,
)

__all__ = [
    "LLMService",
    "LLMTaskType",
    "LLMTaskCategory",
    "LLMResponse",
    "LLMCompletionError",
    "ClinicalEventData",
    "PatientSummary",
    "TASK_CATEGORY",
    "DOCUMENT_LOINC",
    "loinc_for",
    "build_from_config",
    "build_from_config_file",
    "LLMProvider",
    "ProviderResponse",
    "MockProvider",
    "PromptRegistry",
    "PromptSpec",
    "PromptCache",
]
