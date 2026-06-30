"""LLM narrative generator hook (Tier 1 #3 α-min-1 PR1 Task 7).

Default OFF: returns TemplateNarrativeGenerator output unchanged unless
``CLINOSIM_NARRATIVE_LLM=on``. When opt-in, dispatches via
``apply_replacement_strategy`` to the configured LLM provider.

Per spec §7 edge case: if opt-in but provider is unavailable (None) or
raises, falls back to template output with a warning log (does not crash,
does not return empty text).

AD-11 compliance: this module does NOT call Ollama or Anthropic SDKs
directly. Real LLM provider integration via ``clinosim.modules.llm_service``
is deferred to Task 15. The ``LLMProvider`` Protocol (imported from
``replacement_strategy``) is the interface boundary; test code supplies mocks.
"""
from __future__ import annotations

import logging
import os

from clinosim.modules.document.narrative.cache import NarrativeCache, get_default_cache
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.replacement_strategy import (
    LLMProvider,
    apply_replacement_strategy,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import NarrativeContext, NarrativeOutput

logger = logging.getLogger(__name__)


def is_llm_enabled() -> bool:
    """Return True only when CLINOSIM_NARRATIVE_LLM=on (default OFF).

    Case-insensitive: "on", "ON", "On" → True. Any other value → False.
    This gate is read at call time so tests can patch ``os.environ`` cleanly.
    """
    return os.environ.get("CLINOSIM_NARRATIVE_LLM", "").lower() == "on"


class LLMNarrativeGenerator:
    """Stage 2 narrative generator wrapping TemplateNarrativeGenerator.

    Architecture
    ------------
    - Stage 1 (always runs): TemplateNarrativeGenerator produces deterministic
      template output from CIF + disease YAML.
    - Stage 2 (opt-in via env gate): apply_replacement_strategy optionally
      replaces llm_enabled_sections with LLM-generated content.
    - Default OFF: no LLM calls unless CLINOSIM_NARRATIVE_LLM=on.
    - Provider-missing fallback: if opt-in but ``provider`` is None or raises,
      template output is returned with ``generator=template_fallback`` in
      metadata and a WARNING log.

    Parameters
    ----------
    template_generator:
        Stage 1 generator instance. If None, a new ``TemplateNarrativeGenerator``
        is created.
    provider:
        LLMProvider instance (satisfies the Protocol in ``replacement_strategy``).
        May be None (provider-unavailable path). Task 15 will supply a thin
        adapter wrapping ``clinosim.modules.llm_service``.
    cache:
        NarrativeCache instance. Defaults to the module-level singleton. Tests
        should pass an isolated ``NarrativeCache()`` to avoid cross-test state.
    """

    def __init__(
        self,
        template_generator: TemplateNarrativeGenerator | None = None,
        provider: LLMProvider | None = None,
        cache: NarrativeCache | None = None,
    ) -> None:
        self.template = template_generator or TemplateNarrativeGenerator()
        self.provider = provider
        # Default: fresh NarrativeCache per instance to avoid cross-instance
        # contamination. Pass cache=get_default_cache() explicitly when sharing
        # is desired (e.g. long-running enricher calling the same generator
        # across many patients in one process).
        self.cache = cache if cache is not None else NarrativeCache()

    def generate(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Produce NarrativeOutput, optionally with LLM-enhanced sections.

        Execution paths:
        1. Default OFF (CLINOSIM_NARRATIVE_LLM not "on") → template output,
           metadata.generator = "template".
        2. Opt-in, provider=None → template output, generator = "template_fallback",
           WARNING logged.
        3. Opt-in, provider present, provider call succeeds → LLM-enhanced output,
           generator = "llm".
        4. Opt-in, provider raises → template output, generator = "template_fallback",
           WARNING logged.
        """
        # Stage 1: always run template generator
        template_output = self.template.generate(ctx, spec)

        # Gate: default OFF
        if not is_llm_enabled():
            template_output.metadata["generator"] = "template"
            return template_output

        # Provider unavailable
        if self.provider is None:
            logger.warning(
                "CLINOSIM_NARRATIVE_LLM=on but provider unavailable; "
                "falling back to template output (doc_type=%s, lang=%s)",
                ctx.document_type,
                ctx.target_lang,
            )
            template_output.metadata["generator"] = "template_fallback"
            return template_output

        # Stage 2: apply replacement strategy
        try:
            llm_output = apply_replacement_strategy(
                template_output,
                ctx,
                spec,
                self.provider,
                cache_get=self.cache.get,
                cache_put=self.cache.put,
            )
            llm_output.metadata["generator"] = "llm"
            return llm_output
        except Exception as exc:
            logger.warning(
                "LLM provider failed (%s: %s); falling back to template output "
                "(doc_type=%s, lang=%s)",
                type(exc).__name__,
                exc,
                ctx.document_type,
                ctx.target_lang,
            )
            template_output.metadata["generator"] = "template_fallback"
            return template_output
