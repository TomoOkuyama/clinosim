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

from clinosim.modules.document.narrative.cache import (
    cache_key,
    demographics_bucket,
    template_seed_hash,
)
from clinosim.modules.document.narrative.template_generator import _filter_vitals_for_day
from clinosim.modules.llm_service.engine import LLMService, LLMTaskType
from clinosim.types.document import DocumentTypeSpec, NarrativeContext, NarrativeOutput

# v6 (2026-08-16): payload-level localization maps. Values that reach
# the LLM prompt as bare English tokens (encounter_type enum,
# discharge_disposition code) confuse JA narrative generation — LLM saw
# "inpatient" for an outpatient encounter and wrote 「緊急入院」.
_ENCOUNTER_TYPE_JA: dict[str, str] = {
    "outpatient": "外来",
    "inpatient": "入院",
    "emergency": "救急",
    "icu": "ICU",
    "day_surgery": "日帰り手術",
    "rehab_inpatient": "回復期リハビリ入院",
    "prenatal_visit": "妊婦健診",
    "delivery": "分娩",
    "nicu": "NICU",
    "checkup": "健康診断",
}
_DISPOSITION_JA: dict[str, str] = {
    "home": "自宅退院",
    "hosp": "他院転院",
    "other-hcf": "他施設転院",
    "snf": "施設退院",
    "exp": "死亡退院",
}


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


def _build_extra_context(
    ctx: NarrativeContext,
    spec: DocumentTypeSpec,
    template_section_names: set[str] | None = None,
) -> dict[str, str]:
    """Return per-doc-type structured facts to include in the LLM prompt
    context, in addition to the sibling template sections.

    `template_section_names` (v5 dedup): set of template section names
    already going into `context_sections`. Extras that would duplicate
    those sections (chronic_conditions ↔ past_medical_history,
    home_medications ↔ medications_at_home, today_vitals_summary ↔
    objective, etc.) are skipped — template narrative wins on overlap.

    Values are JSON-serialised strings so the prompt payload stays a
    flat dict of readable snippets. Kept small (< 400 tokens total per
    call) to preserve cache hit rate and speed.
    """
    doc_type = getattr(spec, "type_key", "")
    tmpl = template_section_names or set()
    extra: dict[str, str] = {}

    # ---- Universal: cache-bucket demographic + chronic list ---------
    # patient_bucket uses the CACHE-BUCKET granularity (decade + sex)
    # rather than exact age. Preserves cross-patient cache reuse.
    p = ctx.patient
    if p is not None:
        from clinosim.modules.document.narrative.cache import demographics_bucket as _dbucket

        bucket = _dbucket(p)
        if bucket and bucket != "unknown-unknown":
            extra["patient_bucket"] = bucket
        # chronic_conditions: skip when template already renders it as
        # `past_medical_history` (admission_hp only; other doc-types
        # don't get PMH from template so extras carry the chronic list).
        if "past_medical_history" not in tmpl:
            chronic = _get(p, "chronic_conditions", []) or []
            rendered = _render_chronic_list(chronic)
            if rendered:
                extra["chronic_conditions"] = rendered

    # ---- Scenario / trajectory (session-88j v3) --------------------
    # CIF was built around disease_protocol × archetype. Exposing the
    # scenario tag + phase lets the LLM colour the note by phase.
    disease_id = ""
    if ctx.disease_protocol is not None:
        disease_id = getattr(ctx.disease_protocol, "disease_id", "") or ""
    scenario_bits = []
    if disease_id:
        scenario_bits.append(f"disease={disease_id}")
    if ctx.clinical_course_archetype:
        scenario_bits.append(f"archetype={ctx.clinical_course_archetype}")
    if ctx.severity:
        scenario_bits.append(f"severity={ctx.severity}")
    if scenario_bits:
        extra["clinical_scenario"] = " / ".join(scenario_bits)
    if ctx.los_days and ctx.los_days > 0:
        phase = _stay_phase(ctx.day_index, ctx.los_days)
        extra["stay_progress"] = f"day {ctx.day_index} of expected {ctx.los_days} ({phase})"

    # v6 blocker fix (2026-08-16): encounter_type disambiguates outpatient
    # vs inpatient. v5 progress_note vs outpatient_soap prompts diverged
    # by doc_type only — an outpatient SOAP whose chief_complaint was
    # 'follow-up for colonoscopy' was narrated as "緊急入院" because the
    # LLM had no signal to distinguish. Cheap universal field.
    if getattr(ctx, "encounter_type", None) is not None:
        et = ctx.encounter_type
        et_raw = getattr(et, "value", None) or getattr(et, "name", None) or str(et)
        if et_raw and et_raw not in ("None", ""):
            et_raw = str(et_raw).lower()
            # v6 localization: prompt payload should not leak raw English
            # enum tokens into JA narrative generation.
            if ctx.target_lang == "ja":
                extra["encounter_type"] = _ENCOUNTER_TYPE_JA.get(et_raw, et_raw)[:40]
            else:
                extra["encounter_type"] = et_raw[:40]

    enc = ctx.encounter
    if enc is not None:
        # primary_encounter_reason: skip when template already carries
        # `chief_complaint` (admission_hp / discharge_summary / ed_note).
        if "chief_complaint" not in tmpl:
            primary_dx = _get(enc, "primary_diagnosis") or _get(enc, "primary_dx") or _get(enc, "chief_complaint")
            if primary_dx:
                extra["primary_encounter_reason"] = str(primary_dx)[:200]
        # admission_datetime: skip when template already carries
        # `admission_details` (discharge_summary).
        if "admission_details" not in tmpl:
            adm = _get(enc, "admission_datetime") or _get(enc, "admission_date")
            if adm:
                extra["admission_datetime"] = str(adm)[:20]
        los = ctx.los_days
        if los and los > 0:
            extra["length_of_stay_days"] = str(los)

    # ---- v6 inpatient blocker fix (2026-08-16) ---------------------
    # Complications from daily loop (pneumothorax, aspiration_pneumonia,
    # …). Universal — every inpatient doc that references the stay MUST
    # be able to mention them. v5 dropped these entirely so
    # discharge_summary / progress_note / admission_hp appeared bland
    # and clinically hollow.
    complications = list(getattr(ctx, "complications_occurred", []) or [])
    if complications:
        extra["complications_during_stay"] = "; ".join(str(c) for c in complications[:10])

    # ---- Doc-type-specific ----
    if doc_type in ("progress_note", "nursing_shift_note"):
        # Day-N context: today's vital snapshot + active meds
        # todays_vitals_summary skipped only when template's objective
        # already renders vitals (empirically progress_note's objective
        # is exam narrative not vitals — so keep the vitals summary).
        today_vitals = _render_vitals_for_day(ctx.vitals, ctx.day_index, enc)
        if today_vitals:
            extra["todays_vitals_summary"] = today_vitals
        active_meds = _render_active_meds(ctx.medications, ctx.day_index)
        if active_meds:
            extra["active_medications_today"] = active_meds
        # v6 blocker fix: today's abnormal labs (H/L flag). Assessment
        # is LLM-generated for progress_note but v5 context omitted lab
        # H/L flags → LLM never mentioned them.
        abnormal_today = _render_abnormal_labs(ctx.lab_results, day_index=ctx.day_index)
        if abnormal_today:
            extra["abnormal_labs_today"] = abnormal_today
        # v6 blocker fix: supplemental oxygen flag. Prevents "SpO2 89%
        # だが酸素投与なしで安定" self-contradiction (POP-000075 doc-06).
        o2_today = _render_supplemental_oxygen_today(ctx.vitals, ctx.day_index, enc)
        if o2_today:
            extra["supplemental_oxygen_today"] = o2_today
    elif doc_type == "admission_hp":
        # home_medications: skip when template renders medications_at_home.
        if "medications_at_home" not in tmpl:
            home_meds = _get(p, "current_medications", []) or _get(p, "medications", []) or []
            med_names = _render_med_names(home_meds)
            if med_names:
                extra["home_medications"] = med_names
    elif doc_type == "discharge_summary":
        # discharge_medications_list: skip when template renders it.
        if "discharge_medications" not in tmpl:
            dmed = ctx.discharge_medications or []
            dmed_names = _render_med_names(dmed)
            if dmed_names:
                extra["discharge_medications_list"] = dmed_names
        outcome = _get(enc, "discharge_disposition") or _get(enc, "discharge_status")
        if outcome:
            outcome_raw = str(outcome)[:120]
            # v6 localization: `home` → `自宅退院` for JA prompts. LLM
            # was pasting the raw disposition code into JA hospital_course.
            if ctx.target_lang == "ja":
                extra["discharge_outcome"] = _DISPOSITION_JA.get(outcome_raw, outcome_raw)
            else:
                extra["discharge_outcome"] = outcome_raw
        # v6 blocker fix: hospital_course was collapsing to a 1-liner
        # template because LLM had nothing specific to work with.
        # Feed the whole-stay lab/procedure/vitals-extremes summary.
        abnormal_stay = _render_abnormal_labs(ctx.lab_results, day_index=None)
        if abnormal_stay:
            extra["abnormal_labs_during_stay"] = abnormal_stay
        key_procs = _render_key_procedures(ctx.procedures)
        if key_procs:
            extra["key_procedures_performed"] = key_procs
        vitals_range = _render_vitals_range(ctx.vitals)
        if vitals_range:
            extra["vitals_range_during_stay"] = vitals_range
    elif doc_type == "outpatient_soap":
        # home_medications always useful (outpatient template has no
        # medications section). today_vitals_summary: skip when
        # template's `objective` already contains today's vitals numeric
        # summary (outpatient_soap.objective renders BP/HR/RR/SpO2/T
        # verbatim from vitals — same info).
        home_meds = _get(p, "current_medications", []) or _get(p, "medications", []) or []
        med_names = _render_med_names(home_meds)
        if med_names:
            extra["home_medications"] = med_names
        if "objective" not in tmpl:
            today_vitals = _render_vitals_for_day(ctx.vitals, ctx.day_index, enc)
            if today_vitals:
                extra["today_vitals_summary"] = today_vitals
        # v6: same lab flag injection as progress_note — outpatient
        # assessment was ignoring AST H, PT_INR H, Cr H etc.
        abnormal_today = _render_abnormal_labs(ctx.lab_results, day_index=None)
        if abnormal_today:
            extra["abnormal_labs_today"] = abnormal_today
    elif doc_type == "ed_note":
        # chief_complaint_verbatim: skip when template renders
        # chief_complaint (which it does — always in ed_note).
        if "chief_complaint" not in tmpl:
            chief = _get(enc, "chief_complaint")
            if chief:
                extra["chief_complaint_verbatim"] = str(chief)[:200]
        arrival = _get(enc, "arrival_mode") or _get(enc, "admit_source")
        if arrival:
            extra["arrival_mode"] = str(arrival)
        # initial_vitals: physical_exam template is narrative not
        # numeric, so numeric arrival vitals are complementary — keep.
        first_vitals = _render_first_vitals(ctx.vitals)
        if first_vitals:
            extra["initial_vitals"] = first_vitals

    return extra


def _render_chronic_list(chronic: list) -> str:
    """chronic_conditions [{'code','severity','stage','onset_date'}, ...] →
    short comma-separated string."""
    parts = []
    for c in (chronic or [])[:15]:
        if isinstance(c, str):
            parts.append(c)
            continue
        code = _get(c, "code", "") or ""
        stage = _get(c, "stage", "") or ""
        sev = _get(c, "severity", "") or ""
        detail = ""
        if stage and sev:
            detail = f" ({stage}, {sev})"
        elif stage:
            detail = f" ({stage})"
        elif sev:
            detail = f" ({sev})"
        if code:
            parts.append(f"{code}{detail}")
    return "; ".join(parts) if parts else ""


def _render_vitals_for_day(vitals: list, day_index: int, encounter: object | None = None) -> str:
    """Filter vitals to today and pick a summary of key numeric fields.

    v6 (2026-08-16): Uses the shared ``_filter_vitals_for_day`` helper,
    which honours the explicit ``day`` field when present and falls
    back to a timestamp-derived day offset otherwise. The v5 filter
    (day-field only) let admission-day vitals leak into every day's
    context because current CIF vitals leave ``day = None``.
    """
    filtered = _filter_vitals_for_day(vitals, day_index, encounter)
    picks: list[str] = []
    max_pick = 3
    for v in filtered:
        systolic = _get(v, "systolic_bp")
        diastolic = _get(v, "diastolic_bp")
        hr = _get(v, "heart_rate")
        temp = _get(v, "temperature_celsius")
        rr = _get(v, "respiratory_rate")
        spo2 = _get(v, "spo2")
        bits = []
        if temp:
            bits.append(f"T {temp}°C")
        if hr:
            bits.append(f"HR {hr}")
        if systolic and diastolic:
            bits.append(f"BP {systolic}/{diastolic}")
        if rr:
            bits.append(f"RR {rr}")
        if spo2:
            bits.append(f"SpO2 {spo2}%")
        if bits:
            ts = _get(v, "timestamp", "")
            picks.append((str(ts)[:19] + " " if ts else "") + " / ".join(bits))
        if len(picks) >= max_pick:
            break
    return "; ".join(picks) if picks else ""


def _render_supplemental_oxygen_today(vitals: list, day_index: int, encounter: object | None) -> str:
    """If any vital today records supplemental oxygen, return a short
    descriptor for the LLM prompt (device + flow rate).

    v6 (2026-08-16): v5 context omitted this flag entirely — the LLM
    wrote "SpO2 89% だが酸素投与なしで安定" (POP-000075 doc-06)
    contradicting the on_supplemental_oxygen=True field on that day's
    vitals. Feeding the flag lets the prompt's Hard Rules keep the
    narrative consistent with the recorded therapy.
    """
    filtered = _filter_vitals_for_day(vitals, day_index, encounter)
    for v in filtered:
        if not _get(v, "on_supplemental_oxygen"):
            continue
        device = _get(v, "oxygen_delivery_device") or "supplemental O2"
        flow = _get(v, "oxygen_flow_rate_lpm")
        if flow is not None:
            try:
                flow_val = float(flow)
                return f"{device} {flow_val:g} L/min"
            except (TypeError, ValueError):
                pass
        return str(device)
    return ""


def _render_first_vitals(vitals: list) -> str:
    """First-recorded vitals (arrival vitals for ED)."""
    for v in vitals or []:
        systolic = _get(v, "systolic_bp")
        hr = _get(v, "heart_rate")
        temp = _get(v, "temperature_celsius")
        spo2 = _get(v, "spo2")
        bits = []
        if temp:
            bits.append(f"T {temp}°C")
        if hr:
            bits.append(f"HR {hr}")
        if systolic:
            diastolic = _get(v, "diastolic_bp")
            bits.append(f"BP {systolic}/{diastolic}" if diastolic else f"BP {systolic}")
        if spo2:
            bits.append(f"SpO2 {spo2}%")
        if bits:
            return " / ".join(bits)
    return ""


def _render_med_names(meds: list) -> str:
    """List of medication display names, deduplicated, comma-joined."""
    names: list[str] = []
    seen = set()
    for m in meds or []:
        name = _get(m, "name") or _get(m, "display_name") or _get(m, "drug_name") or _get(m, "medication")
        if isinstance(m, str):
            name = m
        if name and name not in seen:
            names.append(str(name)[:60])
            seen.add(name)
        if len(names) >= 12:
            break
    return "; ".join(names) if names else ""


def _render_active_meds(admins: list, day_index: int) -> str:
    """MedicationAdministration records active on the given day. Short list
    of unique drug names given today (progress_note context)."""
    names: list[str] = []
    seen = set()
    for m in admins or []:
        d = _get(m, "day")
        if d is not None and d != day_index:
            continue
        name = _get(m, "drug_name") or _get(m, "medication") or _get(m, "name")
        if name and name not in seen:
            names.append(str(name)[:60])
            seen.add(name)
        if len(names) >= 12:
            break
    return "; ".join(names) if names else ""


def _render_abnormal_labs(lab_results: list, day_index: int | None) -> str:
    """H/L/critical flagged labs, formatted for LLM injection.

    v6 blocker fix: v5 context omitted lab flags entirely so LLM
    assessments ignored AST H, PT_INR H, Cr H etc. When ``day_index``
    is None, returns ALL abnormal labs across the stay
    (discharge_summary use); otherwise filters to that day
    (progress_note use).
    """
    picks: list[str] = []
    max_pick = 8
    for lab in lab_results or []:
        flag = _get(lab, "flag")
        if not flag:
            continue
        d = _get(lab, "day")
        if day_index is not None and d is not None and d != day_index:
            continue
        name = _get(lab, "lab_name") or _get(lab, "name") or ""
        val = _get(lab, "value")
        unit = _get(lab, "unit") or ""
        if not name or val is None:
            continue
        val_str = f"{val}"
        parts = f"{name} {val_str}"
        if unit:
            parts += f" {unit}"
        parts += f" [{flag}]"
        picks.append(parts)
        if len(picks) >= max_pick:
            break
    return "; ".join(picks) if picks else ""


def _render_key_procedures(procedures: list) -> str:
    """List procedures performed during the stay for discharge_summary
    hospital_course context (v6 fix: LLM had no procedure facts to
    reference, producing generic "経過良好" summaries)."""
    names: list[str] = []
    seen: set[str] = set()
    for pr in procedures or []:
        name = _get(pr, "procedure_name") or _get(pr, "name") or _get(pr, "display_name")
        if not name:
            code = _get(pr, "code") or _get(pr, "procedure_code")
            name = str(code) if code else None
        if not name or name in seen:
            continue
        seen.add(name)
        d = _get(pr, "day")
        if d is not None:
            names.append(f"{name} (day {d})")
        else:
            names.append(str(name))
        if len(names) >= 8:
            break
    return "; ".join(names) if names else ""


def _render_vitals_range(vitals: list) -> str:
    """Min/max range of key vitals across the whole stay (BP, HR, T, SpO2).
    Feeds discharge_summary hospital_course so the LLM can say "T peaked
    at 39.1 on D3" instead of generic "経過良好"."""
    if not vitals:
        return ""
    fields = ("systolic_bp", "heart_rate", "temperature_celsius", "spo2")
    minmax: dict[str, tuple[float, float]] = {}
    for v in vitals:
        for f in fields:
            val = _get(v, f)
            if val is None:
                continue
            try:
                num = float(val)
            except (TypeError, ValueError):
                continue
            lo, hi = minmax.get(f, (num, num))
            minmax[f] = (min(lo, num), max(hi, num))
    if not minmax:
        return ""
    labels = {"systolic_bp": "sBP", "heart_rate": "HR", "temperature_celsius": "T", "spo2": "SpO2"}
    parts = []
    for f, (lo, hi) in minmax.items():
        parts.append(f"{labels[f]} {lo:g}-{hi:g}")
    return " / ".join(parts)


def _stay_phase(day_index: int, los_days: int) -> str:
    """Bucket day-of-stay into phase label the LLM can key off in prose."""
    if los_days <= 1:
        return "single-day encounter"
    frac = (day_index + 1) / max(los_days, 1)
    if frac <= 0.34:
        return "early / acute phase"
    if frac <= 0.66:
        return "middle / stabilisation phase"
    if frac < 1.0:
        return "late / pre-discharge phase"
    return "discharge day"
