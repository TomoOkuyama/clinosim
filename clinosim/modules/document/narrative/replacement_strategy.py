"""Replacement strategy dispatch (Tier 1 #3 α-min-1 Task 7; unified in N-chain).

Maps DocumentTypeSpec.stage2_strategy to per-section replacement logic:

- ``"template_only"`` → return template output verbatim (no LLM call).
- ``"template_seed"`` → for each section in spec.llm_enabled_sections, pass the
  template's section text as a seed/context to the LLM prompt (Idea D from spec
  §1.3 decision #13). The LLM receives a prompt that includes the existing
  template-generated text so it can improve upon it rather than generating
  from scratch.
- ``"template_seed_bundle"`` → session-88j Tier 1 uplift. Bundle every
  llm_enabled_sections seed into ONE LLM call (per document, not per section).
  Preserves internal narrative consistency (S↔A↔P coherence, one physician's
  voice) and drops request count to ~1/N compared with per-section. On JSON
  parse failure the caller falls back to per-section replacement so quality
  never regresses to template.
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

    Args:
        template_output: Output from TemplateNarrativeGenerator; used verbatim
            for ``template_only`` strategy or as seed/base for
            ``template_seed``.
        ctx: Narrative context supplying patient + encounter data.
        spec: DocumentTypeSpec carrying ``stage2_strategy`` +
            ``llm_enabled_sections``.
        llm: LLMService instance (AD-11); section replacement goes through
            ``llm.complete_prompt``. Raises ``LLMCompletionError`` on provider
            absence / retry exhaustion — the caller
            (``LLMNarrativeGenerator``) owns the template fallback.
        task_type: LLMTaskType for provider/model selection + accounting.
        language: Target language ("en" / "ja"); selects the narrative_seed
            prompt.
        cache_get: Optional ``NarrativeCache`` getter (layer 1,
            clinical-context key — see module docstring).
        cache_put: Optional ``NarrativeCache`` setter (layer 1).

    Returns:
        ``NarrativeOutput`` with sections potentially replaced by
        LLM-generated text.
    """
    if spec.stage2_strategy == "template_only":
        return template_output
    elif spec.stage2_strategy == "template_seed":
        return _apply_template_seed_strategy(
            template_output,
            ctx,
            spec,
            llm,
            task_type=task_type,
            language=language,
            cache_get=cache_get,
            cache_put=cache_put,
        )
    elif spec.stage2_strategy == "template_seed_bundle":
        return _apply_template_seed_bundle_strategy(
            template_output,
            ctx,
            spec,
            llm,
            task_type=task_type,
            language=language,
            cache_get=cache_get,
            cache_put=cache_put,
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

    # P2-13 PR2a: pick the country-aware LLM-enabled list, then intersect
    # with actually-produced sections. The country-aware call avoids
    # returning US-only section names for a JP document; the intersect
    # keeps us safe if the spec ever lists a section that the template
    # generator did not emit (defensive against ghost sections).
    country = ctx.locale.upper() if getattr(ctx, "locale", None) else "US"
    llm_sections = [s for s in spec.llm_enabled_sections_for(country) if s in new_sections]

    for section in llm_sections:
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

    # FREE_TEXT rejoin (session-88j Tier 1 uplift for progress_note): when
    # the template stored ordered (label, key) pairs in
    # `metadata["raw_text_rejoin"]` — meaning the LLM-eligible sections
    # feed a flat `raw_text` payload rather than a Composition — rebuild
    # `raw_text` from the possibly-replaced sections so the DocumentReference
    # emit path (which reads `raw_text`) sees the LLM content. Composition
    # documents leave this metadata absent and keep the template raw_text
    # untouched (composition FHIR builders read `sections`).
    new_metadata = dict(template_output.metadata)
    new_raw_text = template_output.raw_text
    _rejoin = new_metadata.get("raw_text_rejoin")
    if _rejoin and llm_sections:
        sep = _rejoin.get("separator", "\n")
        order = _rejoin.get("order", [])
        rebuilt_parts: list[str] = []
        for label, key in order:
            body = new_sections.get(key, "")
            rebuilt_parts.append(f"{label} {body}" if label else body)
        new_raw_text = sep.join(rebuilt_parts)

    return NarrativeOutput(
        raw_text=new_raw_text,
        sections=new_sections,
        structured=template_output.structured,
        metadata=new_metadata,
        facts_used=list(template_output.facts_used),
    )


def _apply_template_seed_bundle_strategy(
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
    """Bundle every LLM-eligible section into ONE LLM call per document.

    Contract:
    - Prompt: renders `sections_json_block` (target sections + seeds) and
      `context_json_block` (all other template sections, read-only) so the
      LLM sees the numbers / findings it must NOT contradict.
    - LLM response: JSON `{section_name: rewritten_text, ...}`. On JSON
      parse failure (invalid JSON, missing keys, unexpected keys), the
      strategy falls back to per-section replacement via
      `_apply_template_seed_strategy` so quality never regresses to
      pure template silently.
    - Cache: layer-1 cache key includes a hash of the FULL bundle seed
      map so identical (disease, day, severity, demographics bucket,
      bundle-seed-hash) tuples across patients share one entry.
    - FREE_TEXT rejoin: same post-hook as per-section — if the template
      set `metadata["raw_text_rejoin"]`, rebuild `raw_text` from the
      possibly-replaced sections.
    """
    import json as _json
    import logging as _logging

    _logger = _logging.getLogger(__name__)

    country = ctx.locale.upper() if getattr(ctx, "locale", None) else "US"
    llm_sections = [s for s in spec.llm_enabled_sections_for(country) if s in template_output.sections]
    new_sections = dict(template_output.sections)
    new_metadata = dict(template_output.metadata)

    if not llm_sections:
        # Empty bundle → nothing to do. Return template output unchanged.
        return template_output

    # Layer-1 cache: bundle-scoped key.
    demo_bucket = demographics_bucket(ctx.patient)
    disease_id = ""
    if ctx.disease_protocol is not None:
        disease_id = getattr(ctx.disease_protocol, "disease_id", "") or ""

    # Bundle seed hash covers the ordered (section, seed_text) tuples so
    # differing seeds never collide, while identical bundles share one entry.
    bundle_seed_pairs = tuple((s, new_sections.get(s, "")) for s in llm_sections)
    bundle_seed_repr = "\n".join(f"{s}\x00{t}" for s, t in bundle_seed_pairs)
    bundle_key_section = "bundle:" + "+".join(llm_sections)
    c_key = cache_key(
        disease=disease_id,
        archetype=ctx.clinical_course_archetype,
        day_index=ctx.day_index,
        severity=ctx.severity,
        demographics_bucket=demo_bucket,
        lang=ctx.target_lang,
        section=bundle_key_section,
        seed_hash=template_seed_hash(bundle_seed_repr),
    )

    parsed_bundle: dict[str, str] | None = None
    if cache_get is not None:
        cached = cache_get(c_key)
        if cached is not None:
            try:
                parsed_bundle = _parse_bundle_response(cached, llm_sections)
            except ValueError:
                parsed_bundle = None

    if parsed_bundle is None:
        # Build the prompt: target sections + context sections + output schema.
        sections_json_block = _json.dumps(
            {s: new_sections.get(s, "") for s in llm_sections}, ensure_ascii=False, indent=2
        )
        sections_json_block = f"Target sections (seeds to rewrite):\n{sections_json_block}"

        context_sections = {
            s: new_sections.get(s, "") for s in template_output.sections.keys() if s not in llm_sections
        }
        if context_sections:
            context_json_block = "Context sections (reference only — do NOT modify):\n" + _json.dumps(
                context_sections, ensure_ascii=False, indent=2
            )
        else:
            context_json_block = "Context sections: (none — every template section is being rewritten)"

        output_schema_block = _json.dumps(
            {s: "<rewritten section body>" for s in llm_sections}, ensure_ascii=False, indent=2
        )

        prompt_spec = llm.prompt_registry.get("narrative_seed_bundle", language)
        system_prompt, user_prompt = prompt_spec.render(
            {
                "document_type": spec.type_key,
                "severity": ctx.severity,
                "day_index": ctx.day_index,
                "sections_json_block": sections_json_block,
                "context_json_block": context_json_block,
                "output_schema_block": output_schema_block,
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
        raw_response = response.text or ""

        try:
            parsed_bundle = _parse_bundle_response(raw_response, llm_sections)
        except ValueError as exc:
            _logger.warning(
                "template_seed_bundle: JSON parse failed for %s (%s) — falling back to per-section",
                spec.type_key,
                exc,
            )
            # Safety net: retry via per-section strategy so we never
            # silently regress to pure template on parse issues.
            return _apply_template_seed_strategy(
                template_output,
                ctx,
                spec,
                llm,
                task_type=task_type,
                language=language,
                cache_get=cache_get,
                cache_put=cache_put,
            )

        # Store the RAW response (not the parsed dict) so the cache-hit
        # path can re-parse. This keeps the cache format simple + text-only.
        if cache_put is not None:
            cache_put(c_key, raw_response)

    for section in llm_sections:
        # `_parse_bundle_response` guarantees every requested section key
        # is present (validation happens inside parse); safe direct index.
        new_sections[section] = parsed_bundle[section]

    # FREE_TEXT rejoin — same as per-section path.
    new_raw_text = template_output.raw_text
    _rejoin = new_metadata.get("raw_text_rejoin")
    if _rejoin:
        sep = _rejoin.get("separator", "\n")
        order = _rejoin.get("order", [])
        rebuilt_parts: list[str] = []
        for label, key in order:
            body = new_sections.get(key, "")
            rebuilt_parts.append(f"{label} {body}" if label else body)
        new_raw_text = sep.join(rebuilt_parts)

    return NarrativeOutput(
        raw_text=new_raw_text,
        sections=new_sections,
        structured=template_output.structured,
        metadata=new_metadata,
        facts_used=list(template_output.facts_used),
    )


def _parse_bundle_response(raw: str, expected_keys: list[str]) -> dict[str, str]:
    """Parse a bundle LLM response into a {section: text} dict.

    Accepts:
    - Bare JSON object (per prompt contract).
    - JSON wrapped in ``` fences (defensive — some providers add them
      despite the prompt asking not to).

    Validates that every `expected_keys` entry is present with a non-empty
    string value. Raises `ValueError` on any deviation so the caller can
    fall back to per-section replacement.
    """
    import json as _json
    import re as _re

    if not raw or not raw.strip():
        raise ValueError("empty response")

    text = raw.strip()
    # Strip ```json ... ``` fences if the model ignored the "no fences" rule.
    fence = _re.match(r"^```(?:json)?\s*(.*?)\s*```\s*$", text, _re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        obj = _json.loads(text)
    except _json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object, got {type(obj).__name__}")

    missing = [k for k in expected_keys if k not in obj]
    if missing:
        raise ValueError(f"missing required section keys: {missing}")

    result: dict[str, str] = {}
    for k in expected_keys:
        v = obj[k]
        if not isinstance(v, str):
            raise ValueError(f"section {k!r} value must be a string, got {type(v).__name__}")
        if not v.strip():
            raise ValueError(f"section {k!r} value is empty")
        result[k] = v
    return result
