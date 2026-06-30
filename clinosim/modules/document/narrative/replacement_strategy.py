"""Replacement strategy dispatch (Tier 1 #3 α-min-1 PR1 Task 7).

Maps DocumentTypeSpec.stage2_strategy to per-section replacement logic:

- ``"template_only"`` → return template output verbatim (no LLM call).
- ``"template_seed"`` → for each section in spec.llm_enabled_sections, pass the
  template's section text as a seed/context to the LLM prompt (Idea D from spec
  §1.3 decision #13). The provider receives a prompt that includes the existing
  template-generated text so the LLM can improve upon it rather than generating
  from scratch.
- Unknown strategy → safe default (return template output).

The ``LLMProvider`` Protocol defined here is intentionally minimal:
``generate(prompt: str) -> str``. This differs from ``clinosim.modules.llm_service``
providers (which use ``complete(...)`` returning ``ProviderResponse``). Task 15
will provide a thin adapter wrapping ``llm_service`` to satisfy this Protocol;
for α-min-1, unit tests use ``unittest.mock.MagicMock`` to satisfy it.
"""
from __future__ import annotations

from typing import Callable, Protocol

from clinosim.modules.document.narrative.cache import cache_key, demographics_bucket
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.types.document import NarrativeContext, NarrativeOutput


class LLMProvider(Protocol):
    """Minimal protocol for provider mocking and eventual llm_service wrap.

    Real provider integration via clinosim.modules.llm_service is deferred to
    Task 15. For Task 7 (infrastructure), unit tests supply a MagicMock that
    satisfies this Protocol.
    """

    def generate(self, prompt: str) -> str:
        """Generate text from a prompt string. Raises on error."""
        ...


def apply_replacement_strategy(
    template_output: NarrativeOutput,
    ctx: NarrativeContext,
    spec: DocumentTypeSpec,
    provider: LLMProvider,
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
    provider:
        LLMProvider instance to call for LLM-enabled sections.
    cache_get:
        Optional cache lookup callable ``(key) -> str | None``.
    cache_put:
        Optional cache store callable ``(key, value) -> None``.

    Returns
    -------
    NarrativeOutput with sections potentially replaced by LLM-generated text.
    """
    if spec.stage2_strategy == "template_only":
        return template_output
    elif spec.stage2_strategy == "template_seed":
        return _apply_template_seed_strategy(
            template_output, ctx, spec, provider, cache_get, cache_put
        )
    else:
        # Unknown strategy → safe default: template output unchanged
        return template_output


def _apply_template_seed_strategy(
    template_output: NarrativeOutput,
    ctx: NarrativeContext,
    spec: DocumentTypeSpec,
    provider: LLMProvider,
    cache_get: Callable[[str], str | None] | None,
    cache_put: Callable[[str, str], None] | None,
) -> NarrativeOutput:
    """Idea D: for each llm_enabled_sections, pass template text as seed to LLM.

    Sections not in llm_enabled_sections are passed through unchanged.
    Cache is checked before each provider call; hit → skip provider.

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
      - When ``llm_enabled_sections`` is empty, no provider call is made and the
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

        # Cache lookup
        c_key = cache_key(
            disease=disease_id,
            archetype=ctx.clinical_course_archetype,
            day_index=ctx.day_index,
            severity=ctx.severity,
            demographics_bucket=demo_bucket,
            lang=ctx.target_lang,
            section=section,
        )
        if cache_get is not None:
            cached = cache_get(c_key)
            if cached is not None:
                new_sections[section] = cached
                continue

        # Cache miss — invoke provider with template seed (Idea D)
        prompt = _build_seed_prompt(section, template_text, ctx)
        generated = provider.generate(prompt)

        # Store in cache
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


def _build_seed_prompt(section: str, template_text: str, ctx: NarrativeContext) -> str:
    """Build a prompt that includes the template-generated section text as a seed.

    The prompt instructs the LLM to use the seed as a starting point and improve
    upon it for the given patient context (Idea D: template-as-seed).
    """
    lang_label = "Japanese" if ctx.target_lang == "ja" else "English"
    return (
        f"You are generating a clinical document section '{section}' in {lang_label}.\n"
        f"Patient severity: {ctx.severity}. Day of care: {ctx.day_index}.\n"
        f"Use the following template-generated text as a seed/starting point and "
        f"improve its clinical language and specificity:\n\n"
        f"--- TEMPLATE SEED ---\n{template_text}\n--- END SEED ---\n\n"
        f"Generate an improved version of this section:"
    )
