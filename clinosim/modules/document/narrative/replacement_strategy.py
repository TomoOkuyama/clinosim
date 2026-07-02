"""Replacement strategy dispatch (Tier 1 #3 α-min-1 Task 7; unified in N-chain).

Maps DocumentTypeSpec.stage2_strategy to per-section replacement logic:

- ``"template_only"`` → return template output verbatim (no LLM call).
- ``"template_seed"`` → for each section in spec.llm_enabled_sections, pass the
  template's section text as a seed/context to the LLM prompt (Idea D from spec
  §1.3 decision #13). The LLM receives a prompt that includes the existing
  template-generated text so it can improve upon it rather than generating
  from scratch.
- Unknown strategy → safe default (return template output).

N-2 (N-chain, 2026-07-02): all LLM calls go through
``LLMService.complete_prompt`` (AD-11) — the local ``LLMProvider`` Protocol
that this module used to define is deleted. The service supplies retry,
disk PromptCache, and token/cost accounting; this module supplies the
clinical-context cache (``NarrativeCache``) and the seed prompt.

Two cache layers (complementary, NOT duplicates):

1. ``NarrativeCache`` (this layer, via ``cache_get``/``cache_put``): in-memory,
   keyed by clinical context (disease/archetype/day/severity/demographics
   bucket/lang/section) PLUS a hash of the template seed text (C-1, N-chain
   adv-1). Enables cross-patient reuse — two different patients with the same
   clinical bucket AND identical template seed share one generated section
   without even rendering a prompt; differing seeds never collide.
2. ``PromptCache`` (inside ``LLMService``): on-disk, keyed by
   sha256(system+user+model). Survives process restarts and dedupes exact
   prompt repeats across runs (cost containment for cloud providers).
"""
from __future__ import annotations

from collections.abc import Callable

from clinosim.modules.document.narrative.cache import (
    cache_key,
    demographics_bucket,
    template_seed_hash,
)
from clinosim.modules.llm_service.engine import LLMService, LLMTaskType
from clinosim.types.document import DocumentTypeSpec, NarrativeContext, NarrativeOutput


def apply_replacement_strategy(
    template_output: NarrativeOutput,
    ctx: NarrativeContext,
    spec: DocumentTypeSpec,
    llm: LLMService,
    *,
    task_type: LLMTaskType,
    language: str,
    cache_get: Callable[[str], str | None] | None = None,
    cache_put: Callable[[str, str], None] | None = None,
) -> NarrativeOutput:
    """Dispatch by spec.stage2_strategy and return a NarrativeOutput.

    Parameters
    ----------
    template_output:
        Output from TemplateNarrativeGenerator; used verbatim for
        ``template_only`` strategy or as seed/base for ``template_seed``.
    ctx:
        Narrative context supplying patient + encounter data.
    spec:
        DocumentTypeSpec carrying ``stage2_strategy`` + ``llm_enabled_sections``.
    llm:
        LLMService instance (AD-11); section replacement goes through
        ``llm.complete_prompt``. Raises ``LLMCompletionError`` on provider
        absence / retry exhaustion — the caller (``LLMNarrativeGenerator``)
        owns the template fallback.
    task_type:
        LLMTaskType for provider/model selection + accounting.
    language:
        Target language ("en" / "ja"); selects the narrative_seed prompt.
    cache_get / cache_put:
        Optional ``NarrativeCache`` callables (layer 1, clinical-context key —
        see module docstring).

    Returns
    -------
    NarrativeOutput with sections potentially replaced by LLM-generated text.
    """
    if spec.stage2_strategy == "template_only":
        return template_output
    elif spec.stage2_strategy == "template_seed":
        return _apply_template_seed_strategy(
            template_output, ctx, spec, llm,
            task_type=task_type, language=language,
            cache_get=cache_get, cache_put=cache_put,
        )
    else:
        # Unknown strategy → safe default: template output unchanged
        return template_output


def _apply_template_seed_strategy(
    template_output: NarrativeOutput,
    ctx: NarrativeContext,
    spec: DocumentTypeSpec,
    llm: LLMService,
    *,
    task_type: LLMTaskType,
    language: str,
    cache_get: Callable[[str], str | None] | None,
    cache_put: Callable[[str, str], None] | None,
) -> NarrativeOutput:
    """Idea D: for each llm_enabled_sections, pass template text as seed to LLM.

    Sections not in llm_enabled_sections are passed through unchanged.
    Cache is checked before each LLM call; hit → skip the call.

    ★ Invariant for downstream consumers (e.g. Task 9 FHIR builders):
      - ``sections[<key>]`` is the authoritative content for that section
        (LLM-generated when ``llm_enabled_sections`` includes ``<key>``, else
        template-generated).
      - ``raw_text`` is preserved as the **unmodified template base** — DO NOT
        treat ``raw_text`` as the authoritative narrative for COMPOSITION format
        documents. ``raw_text`` is intended for FREE_TEXT documents only (e.g.
        PROGRESS_NOTE), where no section replacement occurs and the full text is
        rendered directly.
      - If you need a flat reconstruction of all (possibly-replaced) sections,
        join them: ``"\\n\\n".join(output.sections.values())``.
      - When ``llm_enabled_sections`` is empty, no LLM call is made and the
        returned output is byte-identical to ``template_output`` (safe no-op).
    """
    # Build demographic bucket for cache key
    demo_bucket = demographics_bucket(ctx.patient)

    # Derive disease id from protocol (any source — may be None)
    disease_id = ""
    if ctx.disease_protocol is not None:
        disease_id = getattr(ctx.disease_protocol, "disease_id", "") or ""

    # Copy sections so we don't mutate the template output in place
    new_sections = dict(template_output.sections)

    for section in spec.llm_enabled_sections:
        template_text = new_sections.get(section, "")

        # Layer-1 cache lookup (NarrativeCache, clinical-context key).
        # seed_hash (C-1, N-chain adv-1): hashing the template seed text into
        # the key makes a cache hit ⇔ identical seed — wrong-patient reuse is
        # structurally impossible even when the clinical-context components
        # degenerate (e.g. disease_id="" on the production pass path).
        c_key = cache_key(
            disease=disease_id,
            archetype=ctx.clinical_course_archetype,
            day_index=ctx.day_index,
            severity=ctx.severity,
            demographics_bucket=demo_bucket,
            lang=ctx.target_lang,
            section=section,
            seed_hash=template_seed_hash(template_text),
        )
        if cache_get is not None:
            cached = cache_get(c_key)
            if cached is not None:
                new_sections[section] = cached
                continue

        # Cache miss — invoke the LLM with template seed (Idea D) via the
        # unified AD-11 path (retry + PromptCache + cost accounting inside).
        # Prompt ownership (N-3): prompts/{en,ja}/narrative_seed.yaml rendered
        # via the service's PromptRegistry (en fallback for other languages).
        # A missing/invalid prompt raises (FileNotFoundError / KeyError) and
        # propagates to LLMNarrativeGenerator's template fallback.
        prompt_spec = llm.prompt_registry.get("narrative_seed", language)
        system_prompt, user_prompt = prompt_spec.render(
            {
                "section": section,
                "template_text": template_text,
                "severity": ctx.severity,
                "day_index": ctx.day_index,
            }
        )
        response = llm.complete_prompt(
            system_prompt,
            user_prompt,
            language=language,
            task_type=task_type,
            max_tokens=prompt_spec.max_tokens,
            temperature=prompt_spec.temperature,
        )
        generated = response.text or ""

        # Store in layer-1 cache
        if cache_put is not None:
            cache_put(c_key, generated)

        new_sections[section] = generated

    return NarrativeOutput(
        raw_text=template_output.raw_text,
        sections=new_sections,
        structured=template_output.structured,
        metadata=dict(template_output.metadata),
        facts_used=list(template_output.facts_used),
    )
