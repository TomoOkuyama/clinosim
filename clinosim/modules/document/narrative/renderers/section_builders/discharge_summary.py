"""DISCHARGE_SUMMARY (退院時サマリー) section builders — hospital_course /
discharge_diagnoses / discharge_medications / discharge_instructions /
follow_up.

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1i of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

Each builder is a free-standing ``(generator, ctx) -> (text, facts)``
function. The class methods of the same name become thin delegators so
``renderers/composition_sections.py`` (which looks up
``generator._build_<section>`` by name) stays unchanged.

Generator-threaded helpers:
  - ``generator._build_chief_complaint`` (discharge_diagnoses fallback)
  - ``generator._resolve_discharge_instructions`` (discharge_instructions,
    follow_up)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clinosim.codes import lookup as code_lookup
from clinosim.codes import system_key_for
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import strip_protocol_prefix
from clinosim.modules.document.narrative._localization import _localize_complication
from clinosim.types.document import NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


def build_hospital_course(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build hospital_course template seed.

    v6 blocker fix (2026-08-16): v5 returned a single hardcoded
    sentence ("入院 N 日間の治療を経て経過良好。症状は改善し退院となった。"),
    producing 11/11 identical outputs across a p=100 run because
    the LLM had a bland seed AND no factual anchor from context.
    This version enumerates the concrete facts (complications,
    procedures, key med classes) so both the template fallback and
    the LLM prompt see per-patient specificity. The LLM still
    composes the final prose.
    """
    facts: list[str] = []
    lang = ctx.target_lang

    los = ctx.los_days or 1
    parts: list[str] = []

    # Sentence 1: header (LOS + primary reason if present).
    # v7 (2026-08-16 pm): prefer localized fields; skip when JP
    # data only carries the English string ("Dyspnea on exertion,
    # orthopnea, lower extremity edema" leaked into JP discharge
    # summaries in v8). LLM enrichment fills in the reason when
    # the strategy dispatches through it.
    primary_reason = None
    if ctx.encounter is not None:
        # Try the localized ``primary_diagnosis_<lang>`` /
        # ``chief_complaint_<lang>`` slots first; fall back to the
        # base slots. For lang=en both localized slots are typically
        # absent so lookup drops to the base fields on its own.
        primary_reason = _o(ctx.encounter, f"primary_diagnosis_{lang}", None) or _o(
            ctx.encounter, f"chief_complaint_{lang}", None
        )
        if not primary_reason:
            primary_reason = _o(ctx.encounter, "primary_diagnosis", None) or _o(ctx.encounter, "chief_complaint", None)
    if primary_reason:
        parts.append(t("hospital_course.los_head_with_reason", lang, los=los, reason=str(primary_reason)[:80]))
    else:
        parts.append(t("hospital_course.los_head", lang, los=los))

    # Sentence 2: complications (blocker 1 — MUST be surfaced)
    # Issue #848: when a working_diagnoses entry carries an
    # onset_day, prefer the "入院第N日発症" / "developed on hospital
    # day N" rendering — the intra-admission timing is the clinical
    # signal that separates a new-disease event (MI on day 30) from a
    # protocol-standard complication of the primary disease (AKI in
    # sepsis). Falls back to the plain "経過中の合併症" phrasing when
    # no onset day is known (legacy complications_occurred entries).
    comps = list(getattr(ctx, "complications_occurred", []) or [])
    wds = list(getattr(ctx, "working_diagnoses", []) or [])
    wd_by_disease = {str(wd.get("disease_id", "")): wd for wd in wds if isinstance(wd, dict)}
    if comps:
        facts.append("ctx.complications_occurred")
        phrases: list[str] = []
        for c in comps[:6]:
            cid = str(c)
            # Phase 1c-2 (2026-09-22): localize the complication token
            # to JA/EN; unmapped values fall back to a humanised
            # ("_"-stripped) form so novel complications still surface.
            label = _localize_complication(cid, lang)
            wd = wd_by_disease.get(cid)
            onset_day = wd.get("onset_day") if wd else None
            if onset_day is not None and int(onset_day) > 0:
                phrases.append(t("hospital_course.complication_with_onset", lang, day=int(onset_day), label=label))
            else:
                phrases.append(label)
        if wds:
            facts.append("ctx.working_diagnoses")
        sep = t("list_sep.serial", lang)
        parts.append(t("hospital_course.complications_line", lang, list=sep.join(phrases)))

    # Sentence 3: key procedures performed
    proc_names: list[str] = []
    seen: set[str] = set()
    for pr in ctx.procedures or []:
        nm = _o(pr, "procedure_name", None) or _o(pr, "name", None) or _o(pr, "display_name", None)
        if not nm:
            continue
        if nm in seen:
            continue
        seen.add(nm)
        proc_names.append(str(nm))
        if len(proc_names) >= 6:
            break
    if proc_names:
        facts.append("ctx.procedures")
        sep = t("list_sep.serial", lang)
        parts.append(t("hospital_course.procedures_line", lang, list=sep.join(proc_names)))

    # v7 (2026-08-16 pm): closer removed. v6 emitted
    # "治療経過は臨床経過（アーキタイプ）に沿って推移した。" in
    # every JP discharge_summary because the JP-only
    # llm_enabled_sections_jp bug (see DocumentTypeSpec) dropped
    # hospital_course from LLM replacement — so the template seed
    # became the final output and the internal "アーキタイプ" token
    # leaked to every one of 11 patients. Both the union-semantics
    # fix in DocumentTypeSpec and this closer removal are needed.
    facts.append("ctx.los_days")
    return " ".join(parts), facts


def build_discharge_diagnoses(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build discharge_diagnoses from ctx.diagnoses.

    When ``ctx`` is provided ctx.diagnoses is now wired (clinical_diagnosis), so
    this section resolves display text at render time via
    ``clinosim.codes.lookup`` (CIF stores codes only; a bare
    "I63.9" in a JP narrative fails the JP language gate). Format:
    ``<display>（<code>）`` (ja) / ``<display> (<code>)`` (en); when the
    code has no authoritative entry, ``lookup`` returns the code itself
    and the section emits the code alone.
    """
    facts: list[str] = []
    lang = ctx.target_lang

    diagnoses = ctx.diagnoses or []
    if not diagnoses:
        # Fall back to chief complaint
        cc_text, _ = generator._build_chief_complaint(ctx)
        return cc_text, []

    facts.append("ctx.diagnoses")
    parts = []
    for dx in diagnoses:
        code = _o(dx, "discharge_diagnosis_code", "") or _o(dx, "admission_diagnosis_code", "")
        if not code:
            continue
        system = (
            _o(dx, "discharge_diagnosis_system", "")
            or _o(dx, "admission_diagnosis_system", "")
            or system_key_for("diagnosis", ctx.locale.upper())
        )
        display = code_lookup(system, code, ctx.target_lang)
        if display and display != code:
            parts.append(t("list_item.inline_dx_with_code", lang, display=display, code=code))
        else:
            parts.append(code)

    if parts:
        return "; ".join(parts), facts

    # No codes — fall back
    cc_text, _ = generator._build_chief_complaint(ctx)
    return cc_text, []


def build_discharge_medications(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build discharge_medications from ctx.discharge_medications (rx only).

    adv-1 I-1: reads ONLY the normalized discharge_prescription items —
    never ctx.medications (MAR), whose in-hospital entries (ICU drips,
    protocol-prefixed orders) previously leaked into this section.
    Protocol prefixes ("DVT_prophylaxis:", "antipyretic:", ...) are
    stripped via the shared normalization helper (same normalization as the FHIR
    medication builders).
    """
    facts: list[str] = []
    lang = ctx.target_lang
    none_text = t("section_none.discharge_medications", lang)

    meds = getattr(ctx, "discharge_medications", None) or []
    if not meds:
        return none_text, facts

    facts.append("ctx.discharge_medications")
    seen: set[str] = set()
    lines: list[str] = []
    for med in meds:
        drug = _o(med, "drug_name", "") or ""
        drug, _protocol_category = strip_protocol_prefix(drug)
        if not drug:
            continue
        # v7 (2026-08-16 pm): dedup by case-insensitive drug name
        # (kept combo vs mono distinct — "Amoxicillin/Clavulanate"
        # and "Amoxicillin" are pharmacologically different, so
        # collapsing them would be data loss). Fixes only the
        # exact-duplicate variant seen in POP-000075 v8 output
        # ("Amoxicillin" listed twice with identical dose+route+freq).
        norm_key = str(drug).lower().strip()
        if norm_key in seen:
            continue
        seen.add(norm_key)
        # v6 blocker fix (2026-08-16): PrescriptionRecord.items carry
        # dose / route / frequency / days_supply. v5 emitted names
        # only, violating the LLM prompt's REQUIRED specificity spec
        # and leaving discharge_medications indistinguishable across
        # patients. Format: "<drug> <dose> <route> <freq> x<days>d".
        # v9 (2026-08-17 evening): apply JA katakana localization to
        # drug_name. v11 review found 9/11 discharge_summary carried
        # English drug tokens ("Furosemide 20mg PO daily") because
        # this builder never routed through _localize_drug_name.
        display = str(drug)
        # Phase 1c-6 (Category F, 2026-09-23): route dose / route /
        # frequency fields through ``_localize_dosage_terms`` on JA
        # output so 「20mg PO daily」 → 「20mg 経口 1日1回」. Pre-
        # fix, `_localize_drug_name` translated dosage terms only
        # when they appeared inside the drug_name string; the
        # separate ``dose`` / ``route`` / ``frequency`` fields on
        # ``PrescriptionRecord.items`` were concatenated raw, so
        # discharge_medications leaked ``PO`` / ``daily`` / ``TID``
        # / ``q4h`` verbatim into JA output (~545 leaks in the
        # p=10000 audit for `daily` alone).
        # Drug-name katakana + dosage-term localization is a
        # locale-specific data pipeline. `localize_drug_name` is
        # a lang-aware wrapper that returns input verbatim for
        # any lang without a lookup table (today: any
        # non-`"ja"`); `_localize_dosage_terms` is already
        # lang-aware. Single code path across locales.
        from clinosim.modules.output.fhir_r4.lib.localization import (
            _localize_dosage_terms,
            localize_drug_name,
        )

        display = localize_drug_name(display, lang)

        def _term(v: str) -> str:
            try:
                return _localize_dosage_terms(v, lang)
            except Exception:  # noqa: BLE001
                return v

        dose = _o(med, "dose", "") or ""
        route = _o(med, "route", "") or ""
        freq = _o(med, "frequency", "") or ""
        days = _o(med, "days_supply", None)
        bits: list[str] = [display]
        if dose:
            bits.append(_term(str(dose)))
        if route:
            bits.append(_term(str(route)))
        if freq:
            bits.append(_term(str(freq)))
        if days:
            bits.append(t("prescription.days_supply_suffix", lang, days=days))
        lines.append(" ".join(bits))

    if lines:
        return "; ".join(lines), facts
    return none_text, facts


def build_discharge_instructions(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build discharge_instructions using disease-specific override + baseline merge."""
    facts: list[str] = []
    lang = ctx.target_lang

    instructions = generator._resolve_discharge_instructions(ctx)
    facts.append("discharge_instructions.baseline")

    disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol else None
    if disease_id:
        facts.append(f"discharge_instructions.disease_specific.{disease_id}")

    parts = []
    for key, bi_lang in instructions.items():
        text = bi_lang.get(lang) or bi_lang.get("ja") or bi_lang.get("en") or ""
        if text:
            parts.append(text)

    return " ".join(parts), facts


def build_follow_up(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build follow_up section from discharge instructions follow_up entry."""
    lang = ctx.target_lang

    instructions = generator._resolve_discharge_instructions(ctx)
    follow_up_entry = instructions.get("follow_up") or {}
    text = follow_up_entry.get(lang) or follow_up_entry.get("ja") or follow_up_entry.get("en") or ""
    if not text:
        text = t("fallback.follow_up_default", lang)
    return text, ["discharge_instructions.follow_up"]
