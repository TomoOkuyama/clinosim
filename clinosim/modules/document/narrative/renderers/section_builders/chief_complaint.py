"""chief_complaint section builder (common to ADMISSION_HP /
DISCHARGE_SUMMARY / ED_NOTE / OUTPATIENT_SOAP).

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1n of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

Three static helpers close with the builder and move alongside — all
grep-verified to have no callers outside the chief_complaint cluster:
  - ``_disease_canonical_cc`` — single-string canonical CC resolver
    (variant-swap comparison target).
  - ``_maybe_swap_cc_variant`` — Issue #983 variant rotation
    (SHA256-sub-seeded, RNG-neutral) for both disease and encounter
    protocol paths.
  - ``_cc_variant_index`` — deterministic SHA256 sub-seed → index.

Generator-threaded helpers:
  - ``generator._get_ed_note_template`` (ED_NOTE path layer 2 — the
    helper itself stays on the class because other ED builders use it).
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._template_helpers import _pick_localized
from clinosim.modules.document.reference_data_loaders import load_chief_complaint_variants
from clinosim.types.document import DocumentType, NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


def build_chief_complaint(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build chief_complaint section.

    v9 (2026-08-17): resolution order — actual encounter data first,
    then encounter_protocol / disease_protocol template, then a
    hardcoded fallback. v8 skipped encounter.chief_complaint entirely
    and jumped straight to protocol data, so real CIF entries like
    「手/腕の熱傷（部分層）」 or "Severe wheezing" were silently
    replaced by the hardcoded fallback 「発熱・全身倦怠感」 (density
    audit 2026-08-17 found this on every admission_hp / discharge_summary
    / ed_note whose disease_protocol had no `chief_complaint` slot).

    Priority chain:
      1. encounter.chief_complaint / encounter.chief_complaint_ja  (真の CIF、最優先)
      2. encounter_protocol.narrative.ed_note_template.chief_complaint_*
         (ED_NOTE only; encounter-level narrative override)
      3. disease_protocol.chief_complaint                          (疾患 default)
      4. hardcoded fallback「発熱・全身倦怠感」

    Issue #983 variant rotation (JP only): after resolving the raw
    source CC, if it matches the disease canonical CC (i.e. the
    simulator wrote the default), swap in a variant from
    ``chief_complaint_variants.yaml`` picked by a deterministic
    SHA256 sub-seed on (patient_id, encounter_id). Real encounter
    overrides (crush injury body-part strings, ED protocol templates)
    are never touched.
    """
    from clinosim.locale.loader import resolve_localized_display

    facts: list[str] = []
    lang = ctx.target_lang
    fallback = t("chief_complaint.hpi_fallback", lang)

    # Precompute the disease canonical CC — used to decide whether the
    # raw encounter CC is a disease default (variant-eligible) or a
    # real per-encounter override (leave untouched).
    disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol is not None else None
    canonical_disease_cc = _disease_canonical_cc(ctx.disease_protocol, lang)
    # Fall-through slot: encounter_protocol carries its own canonical CC
    # + condition_id for ED "minor complaint" flows (chest_pain_noncardiac,
    # viral_uri, etc.) — the majority of ED CC frequency in the p=2000
    # audit lives here, not in a disease_protocol. When both slots have
    # variants the disease slot wins.
    encounter_condition_id = (
        _o(ctx.encounter_protocol, "condition_id", None) if ctx.encounter_protocol is not None else None
    )
    canonical_encounter_cc = _disease_canonical_cc(ctx.encounter_protocol, lang)

    # 1. Encounter's own chief_complaint is the primary source of truth.
    enc = ctx.encounter
    if enc is not None:
        preferred_key = f"chief_complaint_{lang}"
        for key in (preferred_key, "chief_complaint"):
            raw = _o(enc, key, None)
            if raw:
                raw_str = str(raw)
                # Issue #983 — swap disease-default CCs for a variant.
                swapped, swap_fact = _maybe_swap_cc_variant(
                    raw_str,
                    disease_id,
                    canonical_disease_cc,
                    lang,
                    ctx,
                    encounter_condition_id=encounter_condition_id,
                    canonical_encounter_cc=canonical_encounter_cc,
                )
                facts.append(f"ctx.encounter.{key}")
                if swap_fact:
                    facts.append(swap_fact)
                return swapped, facts

    # 2. ED_NOTE: encounter_protocol.narrative.ed_note_template
    if ctx.document_type == DocumentType.ED_NOTE:
        ed_tmpl = generator._get_ed_note_template(ctx)
        if ed_tmpl is not None:
            text = _pick_localized(ed_tmpl, "chief_complaint", lang, ctx)
            if text:
                facts.append(f"encounter_protocol.narrative.ed_note_template.chief_complaint_{lang}")
                return text, facts
        return fallback, facts

    # 3. disease_protocol.chief_complaint (per-disease default)
    proto = ctx.disease_protocol
    if proto is None:
        return fallback, facts

    cc = _o(proto, "chief_complaint", None)
    if cc is None:
        return fallback, facts

    if isinstance(cc, dict):
        text = resolve_localized_display(cc, lang, fallback=fallback)
        facts_key = f"disease_protocol.chief_complaint.{lang}"
        if text == fallback:
            facts_key += ":fallback"
        facts.append(facts_key)
    else:
        # Plain string (pre-Task-4 format)
        text = str(cc)
        facts.append("disease_protocol.chief_complaint:str")

    # Issue #983 — variant swap for the disease-protocol path too.
    swapped, swap_fact = _maybe_swap_cc_variant(
        text,
        disease_id,
        canonical_disease_cc,
        lang,
        ctx,
        encounter_condition_id=encounter_condition_id,
        canonical_encounter_cc=canonical_encounter_cc,
    )
    if swap_fact:
        facts.append(swap_fact)
    return swapped, facts


def _disease_canonical_cc(disease_protocol: Any, lang: str) -> str | None:
    """Return the disease-protocol canonical chief_complaint (single string).

    Used as the "is this a disease default?" comparison target for
    Issue #983 variant swapping.
    """
    from clinosim.locale.loader import resolve_localized_display

    if disease_protocol is None:
        return None
    cc = _o(disease_protocol, "chief_complaint", None)
    if cc is None:
        return None
    if isinstance(cc, dict):
        return resolve_localized_display(cc, lang, fallback="") or None
    return str(cc)


def _maybe_swap_cc_variant(
    text: str,
    disease_id: str | None,
    canonical_cc: str | None,
    lang: str,
    ctx: NarrativeContext,
    *,
    encounter_condition_id: str | None = None,
    canonical_encounter_cc: str | None = None,
) -> tuple[str, str | None]:
    """Issue #983 — swap disease-default CCs for a per-encounter variant.

    Returns ``(text, fact_or_none)``. When ``fact_or_none`` is not
    ``None`` the swap happened and callers should append it to
    ``facts``. Preserves real per-encounter overrides (burns "手/腕の
    熱傷", stroke fallback strings authored on Encounter, EN locale
    entirely) by returning the original ``text``.

    Two lookup keys are attempted in order:

      1. ``disease_id`` from ``ctx.disease_protocol`` — matches admissions
         for the 32 seeded diseases.
      2. ``encounter_condition_id`` from ``ctx.encounter_protocol`` —
         matches ED "minor complaint" flows (chest_pain_noncardiac,
         viral_uri, elderly_fall etc.). Most ED encounters take this
         path; a swap here breaks the pre-#983 uniform-per-condition
         concentration.
    """
    if lang != "ja" or not text:
        return text, None
    try:
        variants = load_chief_complaint_variants()
    except (OSError, ValueError):
        # Loader errors are non-fatal — narrative must never raise.
        return text, None

    # Priority 1 — disease_protocol
    if disease_id and canonical_cc and text == canonical_cc:
        pool = variants.get(disease_id) or []
        if len(pool) > 1:
            idx = _cc_variant_index(disease_id, ctx, len(pool))
            return pool[idx], f"chief_complaint_variants.{disease_id}[{idx}]"

    # Priority 2 — encounter_protocol
    if encounter_condition_id and canonical_encounter_cc and text == canonical_encounter_cc:
        pool = variants.get(encounter_condition_id) or []
        if len(pool) > 1:
            idx = _cc_variant_index(encounter_condition_id, ctx, len(pool))
            return (
                pool[idx],
                f"chief_complaint_variants.{encounter_condition_id}[{idx}]",
            )

    return text, None


def _cc_variant_index(pool_key: str, ctx: NarrativeContext, pool_size: int) -> int:
    """Deterministic SHA256 sub-seed → variant index.

    Sub-seed on (pool_key, patient_id, encounter_id) — RNG-neutral
    (no ``ctx``-level RNG consumption; matches the pattern documented
    in ``feedback_rng_neutral_additive_field``).
    """
    patient_id = _o(ctx.patient, "patient_id", "") or ""
    encounter_id = _o(ctx.encounter, "encounter_id", "") if ctx.encounter is not None else ""
    seed = f"cc-variant|{pool_key}|{patient_id}|{encounter_id}"
    return int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:4], "big") % pool_size
