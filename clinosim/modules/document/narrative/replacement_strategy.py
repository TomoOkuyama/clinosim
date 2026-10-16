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

import time as _time
from collections.abc import Callable

from clinosim.modules.document.narrative._extra_context_builder import (
    _BIOMETRICS_DOC_TYPES as _BIOMETRICS_DOC_TYPES,
)
from clinosim.modules.document.narrative._extra_context_builder import (
    _HEALTH_LITERACY_DOC_TYPES as _HEALTH_LITERACY_DOC_TYPES,
)
from clinosim.modules.document.narrative._extra_context_builder import (
    _build_extra_context as _build_extra_context,
)
from clinosim.modules.document.narrative._extra_context_builder import (
    _writing_day_of as _writing_day_of,
)
from clinosim.modules.document.narrative._patient_info_renderers import (
    _WRITING_DAY_SCOPE as _WRITING_DAY_SCOPE,
)
from clinosim.modules.document.narrative._patient_info_renderers import (
    _health_literacy_tag as _health_literacy_tag,
)
from clinosim.modules.document.narrative._patient_info_renderers import (
    _localize_token as _localize_token,
)
from clinosim.modules.document.narrative._patient_info_renderers import (
    _render_patient_biometrics as _render_patient_biometrics,
)
from clinosim.modules.document.narrative._patient_info_renderers import (
    _render_patient_demographics as _render_patient_demographics,
)
from clinosim.modules.document.narrative._replacement_localization import (
    _get_lab_name_pattern as _get_lab_name_pattern,
)
from clinosim.modules.document.narrative._replacement_localization import (
    _localize_arrival_mode_ja as _localize_arrival_mode_ja,
)
from clinosim.modules.document.narrative._replacement_localization import (
    _localize_barthel_band_ja as _localize_barthel_band_ja,
)
from clinosim.modules.document.narrative._replacement_localization import (
    _localize_lab_name_ja as _localize_lab_name_ja,
)
from clinosim.modules.document.narrative._replacement_localization import (
    _localize_lab_names_in_sections_ja as _localize_lab_names_in_sections_ja,
)
from clinosim.modules.document.narrative._replacement_localization import (
    _localize_lab_names_in_text_ja as _localize_lab_names_in_text_ja,
)
from clinosim.modules.document.narrative._replacement_localization import (
    _localize_oxygen_device_ja as _localize_oxygen_device_ja,
)
from clinosim.modules.document.narrative._replacement_localization import (
    _localize_risk_level_ja as _localize_risk_level_ja,
)
from clinosim.modules.document.narrative._replacement_localization import (
    _localize_severity_ja as _localize_severity_ja,
)
from clinosim.modules.document.narrative._replacement_localization import (
    _lookup_ja_label as _lookup_ja_label,
)
from clinosim.modules.document.narrative._replacement_localization import (
    localize_lab_name as localize_lab_name,
)
from clinosim.modules.document.narrative._replacement_localization import (
    localize_oxygen_device as localize_oxygen_device,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _render_abnormal_labs as _render_abnormal_labs,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _render_active_meds as _render_active_meds,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _render_chronic_list as _render_chronic_list,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _render_first_vitals as _render_first_vitals,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _render_key_procedures as _render_key_procedures,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _render_lab_carry_forward as _render_lab_carry_forward,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _render_lab_trend_today as _render_lab_trend_today,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _render_med_names as _render_med_names,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _render_newborn_workup_summary as _render_newborn_workup_summary,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _render_supplemental_oxygen_today as _render_supplemental_oxygen_today,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _render_vitals_for_day as _render_vitals_for_day,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _render_vitals_range as _render_vitals_range,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _stay_phase as _stay_phase,
)
from clinosim.modules.document.narrative.cache import (
    cache_key,
    demographics_bucket,
    template_seed_hash,
)
from clinosim.modules.llm_service.engine import LLMService, LLMTaskType
from clinosim.types.document import DocumentTypeSpec, NarrativeContext, NarrativeOutput

# vLLM max-model-len used by the length-truncation retry in
# _apply_template_seed_bundle_strategy. Must match the server's
# `--max-model-len` flag. Boot 12 (2026-09-20) bumped from 16384 to
# 32768 alongside `max_tokens: 8000` in the JP bundle prompt to give the
# retry path enough headroom that discharge_summary edge cases hit by
# Boot 11 (3 length-truncation fallbacks in 80,943 docs) are absorbed
# by the first bundle call rather than escalating to the retry or the
# per-section safety net.
_BUNDLE_RETRY_MAX_MODEL_LEN = 32768


# v8 (2026-08-17): lazy accessor for _localize_drug_name to avoid the
# document→output→document circular import at module load. The
# localization helper only depends on a small YAML at first-call time.
def _load_drug_localizer():  # pragma: no cover — trivial thunk
    """Lazy import of the lang-aware `localize_drug_name` wrapper.
    Returned callable takes `(drug_name, lang)` — a no-op for any
    lang without a lookup table."""
    from clinosim.modules.output.fhir_r4.lib.localization import localize_drug_name as _f

    return _f


# v6 (2026-08-16): payload-level localization maps. Values that reach
# the LLM prompt as bare English tokens (encounter_type enum,
# discharge_disposition code) confuse JA narrative generation — LLM saw
# "inpatient" for an outpatient encounter and wrote 「緊急入院」.
# Phase 1d-2 (2026-09-23): the 16 module-level ``_XXX_JA`` /
# ``_XXX_LABELS`` locale-label tables that used to live here were
# extracted to ``clinosim/locale/shared/llm_prompt_labels.yaml`` so
# adding a new target language is a data change, not a code change.
# The helper signatures below are unchanged from the pre-Phase-1d-2
# API — internal lookups go through
# ``clinosim.locale.loader.load_llm_prompt_labels()`` instead of the
# inline dicts. See the YAML file for the section layout.


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

    # v3 (2026-09-02 prompt double-check): build the SAME structured
    # `context_sections` payload the bundle strategy uses. Passing template
    # `${template_text}` as an LLM seed was retired — the template output
    # is language-drift-prone (a p=10000 JP verify found 34,908 sections
    # emitting English where JA was expected) and anchoring the LLM to
    # that drift defeats the JP prompt's language instruction. Fresh
    # generation grounded strictly in `context_sections` mirrors the
    # bundle strategy's design principle. The per-section fallback path
    # (this function) only fires on bundle-JSON-parse failure, but the
    # SAME grounding contract now applies to both paths.
    context_sections: dict[str, str] = {
        s: new_sections.get(s, "") for s in template_output.sections.keys() if s not in llm_sections
    }
    _extra = _build_extra_context(ctx, spec, template_section_names=set(context_sections.keys()))
    for _k, _v in _extra.items():
        if _k not in context_sections and _v:
            context_sections[_k] = _v

    import json as _json  # local (matches bundle strategy pattern below)

    if context_sections:
        context_json_block = "Context sections (reference only — do NOT modify):\n" + _json.dumps(
            context_sections, ensure_ascii=False, indent=2
        )
    else:
        context_json_block = "Context sections: (none — every template section is being rewritten)"

    for section in llm_sections:
        # Layer-1 cache lookup (NarrativeCache, clinical-context key).
        # seed_hash (C-1, N-chain adv-1): now hashes the section-name +
        # context_sections tuple rather than the retired template seed.
        # Cache hit ⇔ same section-name + same context — wrong-patient
        # reuse is still structurally impossible.
        _cache_repr = section + "\x01" + "\n".join(f"{k}\x00{v}" for k, v in sorted(context_sections.items()))
        c_key = cache_key(
            disease=disease_id,
            archetype=ctx.clinical_course_archetype,
            day_index=ctx.day_index,
            severity=ctx.severity,
            demographics_bucket=demo_bucket,
            lang=ctx.target_lang,
            section=section,
            seed_hash=template_seed_hash(_cache_repr),
        )
        if cache_get is not None:
            cached = cache_get(c_key)
            if cached is not None:
                new_sections[section] = cached
                continue

        # Cache miss — invoke the LLM via the unified AD-11 path (retry +
        # PromptCache + cost accounting inside). Prompt ownership (N-3):
        # prompts/{en,ja}/narrative_seed.yaml v3 (post-2026-09-02 shift
        # to context-driven; no ${template_text} variable). A missing /
        # invalid prompt raises (FileNotFoundError / KeyError) and
        # propagates to LLMNarrativeGenerator's template fallback.
        prompt_spec = llm.prompt_registry.get("narrative_seed", language)
        system_prompt, user_prompt = prompt_spec.render(
            {
                "section": section,
                "context_json_block": context_json_block,
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

    # prompt v11 hard-guard: JA post-processor for EN lab names — see the
    # matching invocation + comment in `_apply_template_seed_bundle_strategy`.
    if language == "ja":
        new_sections = _localize_lab_names_in_sections_ja(new_sections)

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

    # Build context UP-FRONT so the cache key can include it. Without this,
    # two encounters with identical seed sections but different
    # per-encounter context (today's vitals, active_meds, stay_progress)
    # would share a cache entry — the LLM output from encounter 1 would be
    # re-used verbatim on encounter 2 with the wrong facts.
    #
    # Symptom of that pre-fix bug (outpatient_soap POP-000002 v3): visit 2
    # with BP 151/73 kept saying "BP 152/76" (visit 1's cached value) in
    # the assessment.
    context_sections = {s: new_sections.get(s, "") for s in template_output.sections.keys() if s not in llm_sections}
    # v5 dedup: pass the template section names so `_build_extra_context`
    # can skip fields the template already covers (avoids
    # `past_medical_history` template + `chronic_conditions` extra
    # duplicate, `medications_at_home` + `home_medications` duplicate,
    # etc.). Template narrative renderer wins on overlap.
    _extra = _build_extra_context(ctx, spec, template_section_names=set(context_sections.keys()))
    for k, v in _extra.items():
        if k not in context_sections and v:
            context_sections[k] = v

    # Cache key hashes (a) the ORDERED list of LLM section names being
    # generated and (b) the FULL context sections (template siblings +
    # CIF-derived enrichment). The template seed is no longer part of the
    # prompt (session-88j v4 shift to context-driven generation), so it's
    # excluded from the cache key too — cache hit ↔ "same section list +
    # same context" which is precisely what the prompt sees.
    ctx_repr = "\n".join(f"{k}\x00{v}" for k, v in sorted(context_sections.items()))
    sections_repr = "|".join(llm_sections)
    hash_input = sections_repr + "\x01" + ctx_repr
    bundle_key_section = "bundle:" + "+".join(llm_sections)
    c_key = cache_key(
        disease=disease_id,
        archetype=ctx.clinical_course_archetype,
        day_index=ctx.day_index,
        severity=ctx.severity,
        demographics_bucket=demo_bucket,
        lang=ctx.target_lang,
        section=bundle_key_section,
        seed_hash=template_seed_hash(hash_input),
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
        # Build the prompt: target section NAMES (context-driven mode; no
        # template seed leaked as anchor) + context sections + output schema.
        #
        # Session-88j v4-review shift (Q): the template output for LLM-
        # eligible sections is no longer passed as a rewrite seed. Reason:
        # template phrasing (e.g. 「経過観察を継続」) anchors the LLM into
        # generic language and defeats the per-doc-type focus/format
        # instructions. context_sections already carries the CIF facts
        # (chronic list, today's vitals, active meds, scenario, stay
        # progress); the LLM must generate fresh narrative bound by those
        # facts + the prompt's per-doc-type persona / format spec.
        # Template seed content is still used as fallback via the
        # per-section strategy on JSON parse failure.
        _sections_hdr = (
            "Target sections (generate fresh narrative for each — do NOT copy any "
            "template wording; sections MUST be grounded in the context_sections "
            "facts below):\n"
        )
        sections_json_block = _sections_hdr + _json.dumps(list(llm_sections), ensure_ascii=False, indent=2)
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
        # Session-88j: the bundle prompts are authored in English (instruction-
        # following is more reliable than in the target locale), and the
        # OUTPUT language is switched via ${target_language}. Keep the
        # `language` argument to prompt_registry.get unchanged so the same
        # spec is used for JP/EN routes.
        _lang_name = "Japanese" if str(language).lower().startswith("ja") else "English"
        system_prompt, user_prompt = prompt_spec.render(
            {
                "document_type": spec.type_key,
                "severity": ctx.severity,
                "day_index": ctx.day_index,
                "sections_json_block": sections_json_block,
                "context_json_block": context_json_block,
                "output_schema_block": output_schema_block,
                "target_language": _lang_name,
            }
        )
        _t0 = _time.perf_counter()
        response = llm.complete_prompt(
            system_prompt,
            user_prompt,
            language=language,
            task_type=task_type,
            max_tokens=prompt_spec.max_tokens,
            temperature=prompt_spec.temperature,
        )
        _dur_ms = int((_time.perf_counter() - _t0) * 1000)
        raw_response = response.text or ""
        # Per-call throughput logger (session-88j v6-review): logs each
        # bundle call's doc_type / input tokens / output tokens / wall ms
        # so a live `tail -f` on the pass log can compute rolling
        # tok/s without waiting for the final manifest. INFO level to
        # keep default runs quiet unless caller enables INFO on this
        # module. Zero cost when disabled.
        _in = getattr(response, "input_tokens", 0) or 0
        _out = getattr(response, "output_tokens", 0) or 0
        _tps = (_out / (_dur_ms / 1000)) if _dur_ms else 0
        _logger.info(
            "bundle_call doc_type=%s lang=%s dur_ms=%d in_tok=%d out_tok=%d out_tps=%.1f",
            spec.type_key,
            language,
            _dur_ms,
            _in,
            _out,
            _tps,
        )

        try:
            parsed_bundle = _parse_bundle_response(raw_response, llm_sections)
        except ValueError as exc:
            # Length-truncation retry (Boot 11 finding): when vLLM returns
            # finish_reason="length" the response was cut mid-string, breaking
            # JSON. Retry ONCE with an expanded max_tokens budget computed
            # from the observed input token count. Only fires on the ~0.02%
            # of bundle calls that hit the max_tokens ceiling — normal path
            # has zero overhead. On retry success we continue as a normal
            # bundle response; on retry failure or non-length parse errors
            # we fall through to the per-section safety net below.
            finish_reason = getattr(response, "finish_reason", None)
            if finish_reason == "length" and prompt_spec.max_tokens < _BUNDLE_RETRY_MAX_MODEL_LEN:
                input_toks = getattr(response, "input_tokens", 0) or 0
                # Reserve 200-token safety margin below max-model-len.
                retry_budget = _BUNDLE_RETRY_MAX_MODEL_LEN - input_toks - 200
                if retry_budget > prompt_spec.max_tokens:
                    _logger.info(
                        "template_seed_bundle: length-truncated %s (in_tok=%d out=%d), retrying with max_tokens=%d",
                        spec.type_key,
                        input_toks,
                        _out,
                        retry_budget,
                    )
                    retry_response = llm.complete_prompt(
                        system_prompt,
                        user_prompt,
                        language=language,
                        task_type=task_type,
                        max_tokens=retry_budget,
                        temperature=prompt_spec.temperature,
                    )
                    retry_raw = retry_response.text or ""
                    try:
                        parsed_bundle = _parse_bundle_response(retry_raw, llm_sections)
                        # Retry succeeded — treat as a normal bundle response.
                        # Update raw_response so the cache_put below stores
                        # the successful retry, not the truncated original.
                        raw_response = retry_raw
                        response = retry_response
                    except ValueError as retry_exc:
                        _logger.warning(
                            "template_seed_bundle: retry parse failed for %s (%s) — falling back to per-section",
                            spec.type_key,
                            retry_exc,
                        )
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
                else:
                    _logger.warning(
                        "template_seed_bundle: length-truncated %s but retry budget %d ≤ "
                        "original %d (prompt fills model context) — per-section fallback",
                        spec.type_key,
                        retry_budget,
                        prompt_spec.max_tokens,
                    )
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
            else:
                _logger.warning(
                    "template_seed_bundle: JSON parse failed for %s (%s, finish_reason=%s) "
                    "— falling back to per-section",
                    spec.type_key,
                    exc,
                    finish_reason,
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

    # prompt v11 hard-guard (2026-08-20): deterministic post-processor
    # substitutes English lab names (Albumin, Creatinine, Glucose, …)
    # for canonical Japanese katakana in every JA output section. Rule 5 D
    # of the prompt asks the LLM to translate these, but empirical
    # verification (p=10000 s500 N-3 dataset) found 1,063 EN lab hits
    # across 900 new ED_NOTE narratives — the prompt is a soft guardrail
    # only. Standard abbreviations (BUN/CRP/BNP/WBC/HbA1c/eGFR/Cr/PT-INR
    # etc.) are preserved as-is per _LAB_NAME_JA's deliberate omission.
    if language == "ja":
        new_sections = _localize_lab_names_in_sections_ja(new_sections)

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


# ─────────────────────────────────────────────────────────────────
# Session-88j v3: per-doc-type CIF context enrichment
# ─────────────────────────────────────────────────────────────────


def _get(obj, key, default=None):
    """dict / dataclass agnostic getter (mirrors `_shared.get_attr_or_key`)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
