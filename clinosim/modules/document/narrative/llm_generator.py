"""LLM narrative generator (Tier 1 #3 α-min-1 Task 7; wired in N-chain).

Wraps TemplateNarrativeGenerator (Stage 1, always runs) and optionally
replaces ``spec.llm_enabled_sections`` with LLM-generated content via
``apply_replacement_strategy`` → ``LLMService.complete_prompt`` (AD-11).

N-chain (2026-07-02): the ``CLINOSIM_NARRATIVE_LLM`` env gate is DELETED —
opt-in is the explicit CLI choice ``narrate --provider bedrock|ollama|mock``
(which constructs the ``LLMService`` injected here). Three execution paths:

1. ``llm is None`` → template output, ``generator=template_fallback``, WARN.
2. ``llm`` configured, strategy succeeds → strategy output
   (``generator=llm`` when sections were LLM-eligible, else ``template``).
3. strategy raises (provider down, retries exhausted, prompt error) →
   template output, ``generator=template_fallback``, WARN. Never crashes,
   never returns empty text.
"""
from __future__ import annotations

import logging

from clinosim.modules.document.narrative.cache import NarrativeCache
from clinosim.modules.document.narrative.replacement_strategy import (
    apply_replacement_strategy,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.llm_service.engine import LLMService, LLMTaskType
from clinosim.types.document import DocumentTypeSpec, NarrativeContext, NarrativeOutput

logger = logging.getLogger(__name__)


class LLMNarrativeGenerator:
    """Stage 2 narrative generator wrapping TemplateNarrativeGenerator.

    Architecture
    ------------
    - Stage 1 (always runs): TemplateNarrativeGenerator produces deterministic
      template output from CIF + disease YAML.
    - Stage 2 (when ``llm`` is configured): apply_replacement_strategy
      replaces ``llm_enabled_sections`` with LLM-generated content through
      ``LLMService.complete_prompt`` (AD-11 — retry / PromptCache / cost
      accounting live in the service).
    - Fallback: if ``llm`` is None or the strategy raises, template output is
      returned with ``generator=template_fallback`` in metadata + WARNING log.

    Parameters
    ----------
    template_generator:
        Stage 1 generator instance. If None, a new ``TemplateNarrativeGenerator``
        is created.
    llm:
        ``LLMService`` instance (may be None → always-fallback path).
        Constructed by the CLI via ``build_from_config_file`` or, for tests,
        ``LLMService(mode="llm", narrative_provider=MockProvider(), ...)``.
    cache:
        ``NarrativeCache`` instance (layer-1 clinical-context cache — see
        ``replacement_strategy`` module docstring for the two-layer design).
        Defaults to a fresh instance per generator to avoid cross-instance
        contamination; pass a shared instance for cross-patient reuse within
        one narrate run.
    """

    def __init__(
        self,
        template_generator: TemplateNarrativeGenerator | None = None,
        llm: LLMService | None = None,
        cache: NarrativeCache | None = None,
    ) -> None:
        self.template = template_generator or TemplateNarrativeGenerator()
        self.llm = llm
        self.cache = cache if cache is not None else NarrativeCache()

    def generate(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Produce NarrativeOutput, optionally with LLM-enhanced sections."""
        # Stage 1: always run template generator
        template_output = self.template.generate(ctx, spec)

        # Path 1: LLM not configured → template fallback + WARN
        if self.llm is None:
            logger.warning(
                "LLMNarrativeGenerator has no LLMService configured; "
                "falling back to template output (doc_type=%s, lang=%s)",
                ctx.document_type,
                ctx.target_lang,
            )
            template_output.metadata["generator"] = "template_fallback"
            return template_output

        # Path 2: apply replacement strategy
        try:
            task_type = LLMTaskType(ctx.document_type.value)
            llm_output = apply_replacement_strategy(
                template_output,
                ctx,
                spec,
                self.llm,
                task_type=task_type,
                language=ctx.target_lang,
                cache_get=self.cache.get,
                cache_put=self.cache.put,
            )
            # "llm" only when the spec actually routes sections to the LLM —
            # template_only / empty llm_enabled_sections stay "template".
            llm_eligible = (
                spec.stage2_strategy == "template_seed" and bool(spec.llm_enabled_sections)
            )
            llm_output.metadata["generator"] = "llm" if llm_eligible else "template"
            return llm_output
        except Exception as exc:
            # Path 3: strategy failed → template fallback + WARN
            logger.warning(
                "LLM narrative generation failed (%s: %s); falling back to "
                "template output (doc_type=%s, lang=%s)",
                type(exc).__name__,
                exc,
                ctx.document_type,
                ctx.target_lang,
            )
            template_output.metadata["generator"] = "template_fallback"
            return template_output
