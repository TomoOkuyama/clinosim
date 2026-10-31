"""Patient-history section builders — past_medical_history /
medications_at_home / allergies / social_history / family_history /
physical_examination / admission_summary.

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1k of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

Each builder is a free-standing ``(generator, ctx) -> (text, facts)``
function. The class methods of the same name become thin delegators so
``renderers/composition_sections.py`` (which looks up
``generator._build_<section>`` by name) stays unchanged.

Generator-threaded helpers:
  - ``generator._compose_pe_vitals_line`` (physical_examination)
  - ``generator._resolve_physical_exam`` (physical_examination)
  - ``generator._format_physical_exam`` (physical_examination)
  - ``generator._apply_cc_pe_consistency`` (physical_examination)
  - ``generator._build_chief_complaint`` (admission_summary)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clinosim.codes import get_display as code_display
from clinosim.codes import lookup as code_lookup
from clinosim.codes import system_key_for
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._localization import _localize_stage
from clinosim.modules.document.narrative._template_helpers import (
    _GENERIC_FALLBACK_EN,
    _GENERIC_FALLBACK_JA,
    _label,
    _render_home_med_name,
    allergen_display,
)
from clinosim.types.document import NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


def build_past_medical_history(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build past medical history from ctx.patient.chronic_conditions."""
    facts: list[str] = []
    lang = ctx.target_lang
    none_text = t("section_none.past_medical_history", lang)

    patient = ctx.patient
    if patient is None:
        return none_text, facts

    conditions = _o(patient, "chronic_conditions", []) or []
    if not conditions:
        return none_text, facts

    facts.append("ctx.patient.chronic_conditions")
    # Session-88j v3-review fix: resolve ICD code → localised disease
    # display via code_lookup ("icd-10" for JP-native codes / "icd-10-cm"
    # US). Previously the PMH section rendered raw codes ("J45 (Moderate
    # persistent); I10 (Stage 1); …") which read as a coding sheet
    # rather than a clinical PMH. LOOKUP failure falls back to the raw
    # code so the field is never empty.
    #
    # Issue #1333 fix: route the CIF base code through
    # ``map_diagnosis_code`` first so the narrative shows the same
    # billable code (and display) that the FHIR Condition emits. The
    # historical bug was US ``F00`` (dementia base) rendering as
    # "Dementia in Alzheimer disease" (WHO F00 parent-display leaked
    # from icd-10-cm.yaml) while FHIR emitted ``F03.90`` (unspecified
    # dementia) via ``code_mapping_diagnosis/us.yaml`` — narrative
    # ↔ FHIR disagreed on the disease name. Now the narrative looks
    # up the emit-target's display and prints the emit-target code in
    # the trailing ``[code]`` bracket.
    from clinosim.modules.output.fhir_r4.lib.common import map_diagnosis_code

    country = "JP" if ctx.locale.lower() == "jp" else "US"
    icd_system = _label("code_system_icd_display", "primary", lang)
    lines = []
    for cond in conditions:
        code = _o(cond, "code", "")
        stage = _o(cond, "stage", "")
        if not code:
            continue
        # Sex is not always available in ctx.patient shape; pass empty
        # so map_diagnosis_code takes the ``default`` on sex-conditional
        # entries (US C50 defaults to the female leaf per its docstring).
        emit_code = map_diagnosis_code(code, country) or code
        display = code_lookup(icd_system, emit_code, lang) or emit_code
        if display == emit_code:
            # Try 3-char parent (E11.9 → E11) — many mappings live only
            # at the category level.
            base = emit_code.split(".")[0]
            if base != emit_code:
                display = code_lookup(icd_system, base, lang) or emit_code
        # Phase 1c-6 (2026-09-23): localize the severity /
        # persistence descriptor via ``_localize_stage`` so JA
        # emits 「気管支喘息 (軽度持続) [J45]」 rather than
        # 「気管支喘息 (Mild persistent) [J45]」. Mirrors the LLM
        # prompt Rule 5 A authorised table. ~245 leaks in the JP
        # p=10000 audit (Mild / Moderate / Severe / persistent /
        # intermittent).
        stage_display = _localize_stage(str(stage), lang) if stage else ""
        annotation = f" ({stage_display})" if stage_display else ""
        if display and display != emit_code:
            # Format: "気管支喘息 (軽度持続) [J45]" — code
            # trailing for traceability, humans read the display first.
            lines.append(f"{display}{annotation} [{emit_code}]")
        else:
            lines.append(f"{emit_code}{annotation}")
    if lines:
        return "; ".join(lines), facts
    return none_text, facts


def build_medications_at_home(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build home medications from ctx.patient.current_medications."""
    facts: list[str] = []
    lang = ctx.target_lang
    none_text = t("section_none.home_medications", lang)

    patient = ctx.patient
    if patient is None:
        return none_text, facts

    meds = _o(patient, "current_medications", []) or []
    if not meds:
        return none_text, facts

    facts.append("ctx.patient.current_medications")
    # Issue #452 PR 1: `HomeMedication` serializes to dict when the CIF is
    # written to disk and reloaded here in the narrative pass. Extract
    # drug_name explicitly so we don't render a Python dict repr.
    # v9 (2026-08-17): pass lang to enable JA katakana localization.
    return "; ".join(_render_home_med_name(m, lang=lang) for m in meds), facts


def build_allergies(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build allergies section from ctx.allergies.

    Resolves display via code_lookup ( — CIF stores allergen_code
    only, not display text; this mirrors _build_discharge_diagnoses'
    code_lookup pattern in this same file).
    """
    facts: list[str] = []
    lang = ctx.target_lang

    allergies = ctx.allergies or []
    if not allergies:
        return t("fallback.nkda", lang), facts

    # Issue #942: a cohort of exactly one NKA (No Known Allergies)
    # positive-assertion record is narratively equivalent to "no known
    # allergies" — collapse to the NKDA phrasing rather than surfacing
    # the SNOMED "no known allergy" label verbatim.
    if len(allergies) == 1 and bool(_o(allergies[0], "is_nka", False)):
        facts.append("ctx.allergies")
        return t("fallback.nkda", lang), facts

    facts.append("ctx.allergies")
    parts = []
    for allergy in allergies:
        # Skip NKA marker records when mixed alongside real allergies
        # (should not happen with the current enricher, but defensive).
        display = allergen_display(allergy, lang)
        criticality = _o(allergy, "criticality", "") or ""
        if display:
            if criticality:
                crit_str = t("allergy.criticality_suffix", lang, criticality=criticality)
                parts.append(f"{display}{crit_str}")
            else:
                parts.append(display)
    return "; ".join(parts) if parts else (t("fallback.nkda", lang)), facts


def build_social_history(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build social history from patient smoking_status, alcohol_use, occupation."""
    facts: list[str] = []
    lang = ctx.target_lang

    patient = ctx.patient
    if patient is None:
        return t("fallback.generic_fallback", lang), facts

    smoking_status = _o(patient, "smoking_status", "unknown") or "unknown"
    alcohol_use = _o(patient, "alcohol_use", "unknown") or "unknown"
    occupation = _o(patient, "occupation", "") or ""

    smoke_text = _label("smoking", smoking_status, lang, fallback=_label("smoking", "unknown", lang, fallback=""))
    alcohol_text = _label("alcohol", alcohol_use, lang, fallback=_label("alcohol", "unknown", lang, fallback=""))

    parts = []
    if smoke_text:
        key = t("section_label.smoking", lang)
        parts.append(f"{key}: {smoke_text}")
    if alcohol_text:
        key = t("section_label.alcohol", lang)
        parts.append(f"{key}: {alcohol_text}")
    if occupation:
        key = t("section_label.occupation", lang)
        # v6 (2026-08-16): localize occupation token; fall back to
        # raw when unmapped so a novel population value still renders
        # (rather than being dropped silently).
        occ_text = _label("occupation", occupation, lang, fallback=occupation)
        parts.append(f"{key}: {occ_text}")

    facts.append("ctx.patient.smoking_status")
    facts.append("ctx.patient.alcohol_use")
    facts.append("ctx.patient.occupation")

    fallback = t("fallback.generic_fallback", lang)
    return "; ".join(parts) if parts else fallback, facts


def build_family_history(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build family_history section from ``ctx.family_history`` (Issue #982).

    Pre-#982 this returned a hardcoded "特記家族歴なし" placeholder for
    every document, even when the CIF carried real
    FamilyMemberHistoryRecord entries (17,889 FHIR resources in the
    p=2000 audit — narrative rate was 1 distinct string across 171 docs).

    Walks ``ctx.family_history`` (list of ``FamilyMemberHistoryRecord``
    dicts or dataclasses), groups by relationship, translates each
    ``condition_code`` to a display via ``clinosim.codes.get_display``
    (JP → ICD-10-MHLW display; US → ICD-10-CM), and renders a
    relationship-grouped sentence. Falls back to the historical
    "特記家族歴なし" phrase when the CIF has no entries or when every
    relative carries an empty ``condition_codes`` list — the
    placeholder still needs to appear for that legitimate case
    (fam-hx generator emits a relative record even when the sampled
    conditions are empty, so a bare-relative record must not render
    as text-less output).
    """
    facts: list[str] = []
    lang = ctx.target_lang
    fallback = t("fallback.family_history_fallback", lang)

    fams = ctx.family_history or []
    if not fams:
        return fallback, facts

    # Country → code-system key for `get_display` lookup. `system_key_for`
    # is the same helper the FHIR emit-side family_history builder uses,
    # so the narrative and FHIR resource render the same disease label
    # per relative.
    country = "JP" if ctx.locale.lower() == "jp" else "US"
    try:
        icd_system_key = system_key_for("diagnosis", country)
    except KeyError:  # pragma: no cover — kind is hard-coded
        icd_system_key = _label("code_system_icd_lookup", "primary", lang)
    deceased_suffix = t("fallback.family_history_deceased_suffix", lang)
    cond_sep = t("list_sep.serial", lang)
    entry_sep = t("list_sep.space", lang)

    entries: list[str] = []
    for fam in fams:
        rel = str(_o(fam, "relationship", "") or "")
        label = _label("family_relation", rel, lang, fallback=rel or t("common.relative", lang))
        deceased = bool(_o(fam, "deceased", False))
        codes = list(_o(fam, "condition_codes", []) or [])
        displays: list[str] = []
        for code in codes:
            if not code:
                continue
            # get_display falls back to the code string when the
            # display is missing — that surfaces a code rather than an
            # empty entry, better than dropping the relative silently.
            disp = code_display(icd_system_key, str(code), country=country)
            if disp:
                displays.append(str(disp))
        if not displays:
            # A relative with no sampled conditions carries no clinical
            # signal. Skip so we don't render "母 – 。" empty entries.
            continue
        suffix = deceased_suffix if deceased else ""
        joined = cond_sep.join(displays)
        entries.append(t("family_history.entry_line", lang, label=label, suffix=suffix, conditions=joined))

    if not entries:
        return fallback, facts

    facts.append("ctx.family_history")
    prefix = t("section_label.family_history_prefix", lang)
    return prefix + entry_sep.join(entries), facts


def build_physical_examination(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build physical_examination using multi-step fallback chain.

    Issue #979: prepend a JA vital-signs prose line (BP / HR / T / SpO2
    / RR) sourced from CIF ``ctx.vitals`` for the appropriate day
    (admission notes → day 0, discharge summaries → last day, progress
    notes → ``ctx.day_index``). Silently omit the vitals block when
    ``ctx.vitals`` is empty for this day — no placeholder emitted.

    Issue #980: after formatting the per-body-system prose, rewrite
    「意識清明」 clauses to a plausible JCS/GCS phrase when the CIF
    chief_complaint carries an altered-consciousness keyword, and rewrite
    「呼吸音清明」 clauses when the CC carries a severe-dyspnea keyword.
    Deterministic per-encounter pool pick (SHA256), RNG-neutral.
    """
    facts: list[str] = []
    lang = ctx.target_lang

    # Issue #1156: EN PE previously short-circuited to a bare
    # "No special findings" placeholder. The JP-only per-disease
    # ``physical_exam_findings`` YAML content still cannot be reused
    # (would leak CJK), but the vitals line ``_compose_pe_vitals_line``
    # produces a language-neutral prose string ("BP 130/80 mmHg, HR
    # 88/min, T 37.5°C, SpO2 96% (RA), RR 20/min") that reads
    # cleanly in either locale. EN now prepends the vitals block
    # so admission H&P PE carries at least the encounter's
    # objective vitals instead of being blank.
    if lang != "ja":
        vitals_line = generator._compose_pe_vitals_line(ctx)
        if vitals_line:
            facts.append(f"ctx.vitals[day_{ctx.day_index}]")
            return f"Vital signs: {vitals_line}. General: no additional exam findings recorded.", facts
        facts.append("generic:physical_exam_en")
        return _GENERIC_FALLBACK_EN, facts

    phys_exam = generator._resolve_physical_exam(ctx, ctx.clinical_course_archetype, ctx.day_index)
    if phys_exam:
        facts.append(f"physical_exam_findings.{ctx.clinical_course_archetype}.day_{ctx.day_index}")

    text = generator._format_physical_exam(phys_exam, ctx.severity, lang)
    if not text:
        text = _GENERIC_FALLBACK_JA

    # #980: rewrite contradicted clauses BEFORE #979 prepend so the
    # rewrite operates on the "labelled clause" shape produced by
    # `_format_physical_exam` (see `_rewrite_pe_clause` docstring).
    text, cc_facts = generator._apply_cc_pe_consistency(text, ctx)
    facts.extend(cc_facts)

    # #979: prepend vital-signs prose line for this day.
    vitals_line = generator._compose_pe_vitals_line(ctx)
    if vitals_line:
        facts.append(f"ctx.vitals[day_{ctx.day_index}]")
        text = f"バイタルサイン: {vitals_line}。{text}"

    return text, facts


def build_admission_summary(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build admission_summary for DISCHARGE_SUMMARY."""
    facts: list[str] = []
    lang = ctx.target_lang

    cc_text, cc_facts = generator._build_chief_complaint(ctx)
    facts.extend(cc_facts)

    text = t("admission_summary.head_line", lang, cc=cc_text, day=ctx.day_index + 1)

    return text, facts
