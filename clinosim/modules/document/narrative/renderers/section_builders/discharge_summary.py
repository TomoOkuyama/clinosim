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
  - ``section_builder("chief_complaint")`` (discharge_diagnoses fallback)
  - ``generator._resolve_discharge_instructions`` (discharge_instructions,
    follow_up)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clinosim.countries import country_code
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import strip_protocol_prefix
from clinosim.modules.document.narrative._localization import _localize_complication
from clinosim.modules.document.narrative._prescription_line import prescription_bits
from clinosim.modules.document.narrative.renderers._shared_helpers import diagnosis_coded
from clinosim.modules.document.narrative.renderers.section_builders._registry import section, section_builder
from clinosim.types.document import NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


@section("hospital_course")
def build_hospital_course(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build hospital_course template seed (see :func:`compose_hospital_course`)."""
    return compose_hospital_course(ctx)


def compose_hospital_course(ctx: NarrativeContext, *, with_results: bool = True) -> tuple[str, list[str]]:
    """The hospital course of a stay: the shared body of the discharge
    summary's course and the referral letter's clinical course (Issue #3268).
    ``with_results=False`` leaves out the significant-results sentence, for a
    document that states the results in a section of their own.

    The length of stay with the primary reason, then the sentences of
    ``narrative/_hospital_course.py`` (Issue #3246): readmission, main
    treatments by drug tier, procedures with dates, complications with the
    hospital day of onset, significant results with their treatment,
    medication changes from admission and the condition at discharge. The
    LLM, when enabled, composes its prose from these facts.
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
        # Issue #3390: the complaint is the encounter's canonical one.
        from clinosim.modules.document.narrative.renderers.section_builders.chief_complaint import (
            encounter_chief_complaint,
            raw_encounter_chief_complaint,
        )

        cc = encounter_chief_complaint(ctx)
        primary_reason = _o(ctx.encounter, f"primary_diagnosis_{lang}", None) or (
            cc if raw_encounter_chief_complaint(ctx, localized_only=True) else None
        )
        if not primary_reason:
            primary_reason = _o(ctx.encounter, "primary_diagnosis", None) or cc
    if primary_reason:
        parts.append(t("hospital_course.los_head_with_reason", lang, los=los, reason=str(primary_reason)[:80]))
    else:
        parts.append(t("hospital_course.los_head", lang, los=los))

    # Issue #3246: the course itself — readmission, main treatments,
    # procedures with dates, complications with onset, significant results
    # and their treatment, medication changes, condition at discharge. Each
    # sentence is written only when the record has its facts.
    from clinosim.modules.document.narrative import _hospital_course as hc

    builders = (
        hc.readmission_sentence,
        hc.treatments_sentence,
        hc.procedures_sentence,
        hc.complications_sentence,
        hc.notable_labs_sentence,
        hc.medication_changes_sentence,
        hc.newborn_prophylaxis_sentence,
        hc.discharge_condition_sentence,
    )
    for build in builders:
        if build is hc.notable_labs_sentence and not with_results:
            continue
        sentence, fact = build(ctx)
        if sentence:
            parts.append(sentence)
            facts.append(fact)

    # Issue #3245: a newborn's screening results, once resulted (the H&P and
    # the early notes cite only what existed then).
    from clinosim.modules.document.narrative.renderers._composers import newborn_screening_to_date

    screening = newborn_screening_to_date(ctx)
    if screening:
        parts.append(t("progress.newborn_screening", lang, list=screening))
        facts.append("ctx.newborn_workup")

    facts.append("ctx.los_days")
    return t("list_sep.sentence_gap", lang).join(parts), facts


@section("discharge_diagnoses")
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
        cc_text, _ = section_builder("chief_complaint")(generator, ctx)
        return cc_text, []

    facts.append("ctx.diagnoses")
    parts = []
    for dx in diagnoses:
        code = _o(dx, "discharge_diagnosis_code", "") or _o(dx, "admission_diagnosis_code", "")
        if not code:
            continue
        # Issue #3259: the emitted code and its prose name.
        code, display = diagnosis_coded(code, country_code(ctx.locale), ctx.target_lang)
        if display and display != code:
            parts.append(t("list_item.inline_dx_with_code", lang, display=display, code=code))
        else:
            parts.append(code)

    if parts:
        primary = "; ".join(parts)
        secondary = _secondary_diagnoses(ctx, diagnoses)
        if secondary:
            facts.append("ctx.working_diagnoses")
            return t(
                "discharge_diagnoses.with_secondary",
                lang,
                primary=primary,
                list=t("list_sep.serial", lang).join(secondary),
            ), facts
        return primary, facts

    # No codes — fall back
    cc_text, _ = section_builder("chief_complaint")(generator, ctx)
    return cc_text, []


def _secondary_diagnoses(ctx: NarrativeContext, diagnoses: list) -> list[str]:
    """The diagnoses that arose during the stay (Issue #3246): each working
    diagnosis the FHIR output codes as a secondary Condition
    (``working_diagnosis_code``, the code and display the output emits), then
    the in-hospital complications that no listed code already names, by name
    and without a code (they have no Condition). The final diagnosis's
    ICD-10 category (discharge code, else admission code) is not repeated. The
    stay's secondary diagnosis codes come first (Issue #3392)."""
    from clinosim.modules.disease.protocol import working_diagnosis_code
    from clinosim.modules.document.reference_data_loaders import load_death_cause_chain

    lang = ctx.target_lang
    country = country_code(ctx.locale)
    sex = str(_o(ctx.patient, "sex", "") or "") if ctx.patient is not None else ""
    seen: set[str] = set()
    for dx in diagnoses:
        code = str(_o(dx, "discharge_diagnosis_code", "") or "") or str(_o(dx, "admission_diagnosis_code", "") or "")
        if code:
            seen.add(code.split(".")[0])
    items: list[str] = []
    # Issue #3392: the secondary diagnosis codes of the stay (the co-disease of
    # a mixed admission), which the FHIR output codes as secondary Conditions.
    for dx in diagnoses:
        for code in _o(dx, "secondary_diagnosis_codes", []) or []:
            code = str(code or "")
            if not code or code.split(".")[0] in seen:
                continue
            seen.add(code.split(".")[0])
            emitted, display = diagnosis_coded(code, country, lang, sex)
            items.append(
                t("list_item.inline_dx_with_code", lang, display=display, code=emitted)
                if display != emitted
                else emitted
            )
    for wd in ctx.working_diagnoses or []:
        code = working_diagnosis_code(str(_o(wd, "disease_id", "") or ""))
        if not code or code.split(".")[0] in seen:
            continue
        seen.add(code.split(".")[0])
        emitted, display = diagnosis_coded(code, country, lang, sex)
        items.append(
            t("list_item.inline_dx_with_code", lang, display=display, code=emitted) if display != emitted else emitted
        )
    # A complication token's diagnosis code, where one names it, keeps a
    # complication already listed as a coded diagnosis from repeating.
    complication_codes = load_death_cause_chain().immediate_cause_complications
    names: set[str] = set()
    for event in ctx.complications_events or []:
        token = str(_o(event, "name", "") or "")
        key = "_".join(token.strip().lower().split())
        code = complication_codes.get(key) or ""
        if not token or (code and code.split(".")[0] in seen):
            continue
        label = _localize_complication(token, lang)
        if label and label not in names:
            names.add(label)
            items.append(label)
            if code:
                seen.add(code.split(".")[0])
    return items


@section("discharge_medications")
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
        from clinosim.locale.free_text import (
            localize_drug_name,
        )

        display = localize_drug_name(display, lang)

        bits: list[str] = [display, *prescription_bits(med, lang, drug_name=display)]
        lines.append(" ".join(bits))

    if lines:
        return "; ".join(lines), facts
    return none_text, facts


@section("discharge_instructions")
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
        # Issue #2273: missing language falls back to English, never Japanese.
        # Issue #3254: a text emptied by sentence de-duplication stays empty.
        text = bi_lang[lang] if lang in bi_lang else bi_lang.get("en") or ""
        if text:
            parts.append(text)

    return " ".join(parts), facts


@section("follow_up")
def build_follow_up(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build follow_up section from discharge instructions follow_up entry."""
    lang = ctx.target_lang

    instructions = generator._resolve_discharge_instructions(ctx)
    follow_up_entry = instructions.get("follow_up") or {}
    text = follow_up_entry.get(lang) or follow_up_entry.get("en") or ""
    if not text:
        text = t("fallback.follow_up_default", lang)
    return text, ["discharge_instructions.follow_up"]
