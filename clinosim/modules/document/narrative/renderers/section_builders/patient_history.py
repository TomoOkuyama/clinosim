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
  - ``section_builder("chief_complaint")`` (admission_summary)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from clinosim.codes import display as registry_display
from clinosim.codes import lookup as code_lookup
from clinosim.codes import system_key_for
from clinosim.codes.hl7_encounter import AdmitSource
from clinosim.codes.icd10 import condition_label
from clinosim.countries import country_code, has_authored_narrative, lang_for
from clinosim.locale.i18n import t
from clinosim.locale.loader import map_family_history_code
from clinosim.locale.loader import narrative_label as _label
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._as_of import recorded_by
from clinosim.modules.document.narrative._localization import _localize_stage
from clinosim.modules.document.narrative._narrative_utils import is_neonate
from clinosim.modules.document.narrative._outpatient_results import (
    latest_lab_stage,
    prior_lab_values,
    stage_from_pending_lab,
)
from clinosim.modules.document.narrative._template_helpers import (
    _render_home_med_name,
    allergen_display,
)
from clinosim.modules.document.narrative.renderers._composers import pe_vitals_reading
from clinosim.modules.document.narrative.renderers._disease_exam import exam_findings
from clinosim.modules.document.narrative.renderers._exam_agreement import arrival_vital_states
from clinosim.modules.document.narrative.renderers._resolvers import resolve_neonatal_exam
from clinosim.modules.document.narrative.renderers._shared_helpers import (
    diagnosis_coded,
)
from clinosim.modules.document.narrative.renderers.section_builders._registry import section, section_builder
from clinosim.types.document import NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


@section("past_medical_history")
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
    # The PMH line names each condition by the prose name of the code the
    # output emits and prints that code ("2型糖尿病 (HbA1c 7.9%) [E11.9]";
    # Issue #1333 / #2994: US F00 → F03.90; Issue #3259: the clinical name,
    # not the classification title — 「本態性（原発性＜一次性＞）高血圧（症）」 —
    # which only the FHIR coding.display carries). A code with no name
    # prints alone so the field is never empty.
    country = country_code(ctx.locale)
    sex = str(_o(patient, "sex", "") or "")
    lines = []
    known_labs = prior_lab_values(ctx, include_own=True)
    for cond in conditions:
        code = _o(cond, "code", "")
        stage = _o(cond, "stage", "")
        if not code:
            continue
        # Issue #3273: a stage a lab states (CKD G category, HbA1c) is the
        # latest result known at the note, not the stage stored on the problem
        # list.
        # Issue #3396: a stored stage restated from a result reported after
        # the note was authored is not known to it.
        known_stage = latest_lab_stage(str(code), str(stage or ""), known_labs)
        if known_stage:
            stage = known_stage
        elif stage and stage_from_pending_lab(ctx, str(code), str(stage)):
            stage = ""
        emit_code, display = diagnosis_coded(code, country, lang, sex)
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


def home_medications_at_admission(ctx: NarrativeContext) -> tuple[list[Any], str]:
    """The patient's home medications when the stay began and the fact that
    names their source (Issue #2995): the record's admission snapshot, else
    (a record written without one) the patient's ``current_medications``,
    which is the list at the end of the simulation."""
    snapshot = getattr(ctx, "home_medications_at_admission", None)
    if snapshot is not None:
        return list(snapshot), "ctx.home_medications_at_admission"
    patient = ctx.patient
    meds = (_o(patient, "current_medications", []) or []) if patient is not None else []
    return list(meds), "ctx.patient.current_medications"


@section("medications_at_home")
def build_medications_at_home(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build home medications from the medications at admission (Issue #2995)."""
    facts: list[str] = []
    lang = ctx.target_lang
    none_text = t("section_none.home_medications", lang)

    meds, source = home_medications_at_admission(ctx)
    if not meds:
        return none_text, facts

    facts.append(source)
    # Issue #452 PR 1: `HomeMedication` serializes to dict when the CIF is
    # written to disk and reloaded here in the narrative pass. Extract
    # drug_name explicitly so we don't render a Python dict repr.
    # v9 (2026-08-17): pass lang to enable JA katakana localization.
    return "; ".join(_render_home_med_name(m, lang=lang) for m in meds), facts


@section("allergies")
def build_allergies(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build allergies section from ctx.allergies (see :func:`allergy_text`)."""
    return allergy_text(ctx)


def allergy_text(ctx: NarrativeContext) -> tuple[str, list[str]]:
    """The patient's allergies in the note language: each allergen with its
    criticality, or the no-known-allergies phrase. Also read by the ED notes
    (Issue #3244).

    Resolves display via code_lookup ( — CIF stores allergen_code
    only, not display text; this mirrors build_discharge_diagnoses'
    code_lookup pattern in this same file).
    """
    facts: list[str] = []
    lang = ctx.target_lang

    allergies = getattr(ctx, "allergies", None) or []
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
                crit_str = t(
                    "allergy.criticality_suffix",
                    lang,
                    criticality=_label("allergy_criticality", str(criticality), lang),
                )
                parts.append(f"{display}{crit_str}")
            else:
                parts.append(display)
    return "; ".join(parts) if parts else (t("fallback.nkda", lang)), facts


@section("social_history")
def build_social_history(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build social history from patient smoking_status, alcohol_use, occupation."""
    facts: list[str] = []
    lang = ctx.target_lang

    patient = ctx.patient
    if patient is None:
        return t("fallback.generic_fallback", lang), facts

    if is_neonate(ctx):
        return _neonatal_social_history(ctx, lang)

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


def _neonatal_social_history(ctx: NarrativeContext, lang: str) -> tuple[str, list[str]]:
    """Issue #3260: a neonate's social history is the birth history (born in
    this hospital, Apgar scores) and the caregiver, not smoking / alcohol /
    occupation. Only what the CIF records is stated; the delivery mode is
    on the mother's record and is not repeated here."""
    facts: list[str] = []
    birth: list[str] = []
    if _o(ctx.encounter, "admit_source", "") == AdmitSource.BORN:
        birth.append(t("neonate_history.born_here", lang))
        facts.append("ctx.encounter.admit_source")
    workup = ctx.newborn_workup or {}
    a1, a5 = workup.get("apgar_1min"), workup.get("apgar_5min")
    if a1 is not None and a5 is not None:
        birth.append(t("neonate_history.apgar", lang, a1=a1, a5=a5))
        facts.append("ctx.newborn_workup.apgar")
    # Issue #3245: the birth data the newborn's record holds (the mother's
    # delivery: gestational age, mode of delivery; the newborn profile's birth
    # weight and length). An item the record lacks is not written; without any
    # the birth history says so.
    info = workup.get("birth") or {}
    days = info.get("gestational_age_days")
    if isinstance(days, int) and days > 0:
        birth.append(t("neonate_history.gestational_age", lang, weeks=days // 7, days=days % 7))
        facts.append("ctx.newborn_workup.birth.gestational_age_days")
    if info.get("delivery_mode"):
        birth.append(t(f"neonate_history.delivery_mode.{info['delivery_mode']}", lang))
        facts.append("ctx.newborn_workup.birth.delivery_mode")
    weight, length = workup.get("birth_weight_kg"), workup.get("birth_length_cm")
    if weight:
        birth.append(t("neonate_history.birth_weight", lang, kg=f"{float(weight):g}"))
        facts.append("ctx.patient.weight_kg")
    if length:
        birth.append(t("neonate_history.birth_length", lang, cm=f"{float(length):g}"))
        facts.append("ctx.patient.height_cm")
    if not (info or weight or length):
        birth.append(t("neonate_history.birth_data_not_recorded", lang))
    parts: list[str] = []
    if birth:
        parts.append(t("neonate_history.birth_line", lang, items=t("list_sep.serial", lang).join(birth)))
    maternal = _maternal_history(ctx, info)
    if maternal:
        parts.append(maternal)
        facts.append("ctx.newborn_workup.birth.maternal_condition_codes")
    relationship = _o(_o(ctx.patient, "contact", None), "emergency_contact_relationship", "") or ""
    caregiver = registry_display("hl7-v3-rolecode", relationship, lang) if relationship else None
    if caregiver:
        parts.append(t("neonate_history.caregiver_line", lang, caregiver=caregiver))
        facts.append("ctx.patient.contact.emergency_contact_relationship")
    if not parts:
        return t("fallback.generic_fallback", lang), facts
    return "; ".join(parts), facts


def _maternal_history(ctx: NarrativeContext, info: dict[str, Any]) -> str:
    """The mother's age and chronic conditions at the delivery, as the newborn's
    maternal history (Issue #3245); ``""`` when the birth record has none."""
    from clinosim.modules.document.narrative.renderers._shared_helpers import chronic_condition_label

    lang = ctx.target_lang
    country = country_code(ctx.locale)
    labels = [
        chronic_condition_label(str(code), country, lang, "female") or str(code)
        for code in info.get("maternal_condition_codes") or []
    ]
    items: list[str] = []
    if info.get("maternal_age"):
        items.append(t("neonate_history.maternal_age", lang, age=info["maternal_age"]))
    if labels:
        items.append(t("list_sep.serial", lang).join(labels))
    return t("neonate_history.maternal_line", lang, items=t("list_sep.serial", lang).join(items)) if items else ""


@section("family_history")
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

    # Country → code-system key for `lookup` lookup. `system_key_for`
    # is the same helper the FHIR emit-side family_history builder uses,
    # so the narrative and FHIR resource render the same disease label
    # per relative.
    country = country_code(ctx.locale)
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
            # Issue #2994: the label of the condition the FamilyMemberHistory
            # codes (E78 → E78.5 "Dyslipidemia", not the E78 category
            # title); lookup falls back to the code string when the
            # display is missing — that surfaces a code rather than an
            # empty entry, better than dropping the relative silently.
            fam_code = map_family_history_code(str(code), country)
            disp = condition_label(fam_code, country, lang_for(country)) or code_lookup(
                icd_system_key, fam_code, lang_for(country)
            )
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


@section("physical_examination")
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
    neonate = is_neonate(ctx)
    vitals_line = generator._compose_pe_vitals_line(ctx)
    if vitals_line:
        facts.append(f"ctx.vitals[day_{ctx.day_index}]")

    # Issue #3245: the exam of the admission day is the admitting disease's
    # (disease_exam.yaml, in the document language) with the vital-sign
    # clauses the quoted reading contradicts left out; later days (and a
    # disease without one) use the protocol / baseline exam, written for
    # languages with authored narrative content.
    findings: dict[str, str] = {}
    source = ""
    if neonate:
        # Issue #3260: the newborn exam set carries every language.
        findings = {
            k: v for k, v in resolve_neonatal_exam(ctx, ctx.day_index).items() if isinstance(v, str) and v.strip()
        }
        source = "physical_exam_findings.neonatal"
    else:
        reading = pe_vitals_reading(ctx)
        states = arrival_vital_states(reading, ctx) if reading is not None else {}
        findings, source = exam_findings(generator, ctx, reading, states)
    if source:
        facts.append(source)

    text = generator._format_physical_exam(findings, ctx.severity, lang)
    if not has_authored_narrative(lang):
        # English: the findings of the disease; none authored for the day says
        # so (the vitals line alone carries the reading).
        if not text:
            if not vitals_line:
                facts.append("generic:physical_exam_en")
                return t("fallback.generic_fallback", lang), facts
            text = t("physical_exam.no_other_findings", lang)
        return (
            t("ed_physical_exam.vitals_prepend", lang, vitals=vitals_line, text=text) if vitals_line else text
        ), facts

    if not text:
        text = t("fallback.generic_fallback", lang)

    # #980: rewrite contradicted clauses BEFORE #979 prepend so the
    # rewrite operates on the "labelled clause" shape produced by
    # `_format_physical_exam` (see `_rewrite_pe_clause` docstring).
    text, cc_facts = generator._apply_cc_pe_consistency(text, ctx)
    facts.extend(cc_facts)

    # #979: prepend vital-signs prose line for this day.
    if vitals_line:
        text = t("ed_physical_exam.vitals_prepend", lang, vitals=vitals_line, text=text)

    return text, facts


@section("admission_results")
def build_admission_results(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """The results the admission H&P cites (Issue #3245): the abnormal
    laboratory results and the imaging / ECG reports available at the note's
    authored time (Issue #3241) — a result reported later is not in the note.
    The labs are worded as the progress-note Assessment words them (flag,
    previous value, the abnormality a result names); a stay with lab orders
    but no result back yet says the results are pending."""
    from clinosim.locale.loader import imaging_exam_display
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules
    from clinosim.modules.document.narrative._notable_labs import notable_lab_entries

    facts: list[str] = []
    lang = ctx.target_lang
    as_of = getattr(ctx, "authored_datetime", None)
    sep = t("list_sep.semicolon", lang)
    parts: list[str] = []

    known_labs = recorded_by(list(ctx.lab_results or []), as_of, "result_datetime")
    if known_labs:
        facts.append("ctx.lab_results.known_at_note_time")
        entries = notable_lab_entries(
            known_labs,
            _o(ctx.encounter, "admission_datetime", None),
            None,
            lang,
            limit=notable_lab_rules().max_items.note,
            as_of=as_of,
        )
        if entries:
            parts.append(t("admission_results.labs_abnormal", lang, list=sep.join(entries)))
        else:
            parts.append(t("admission_results.labs_normal", lang, n=len(known_labs)))
    elif any(str(_o(o, "order_type", "") or "").lower() == "lab" for o in ctx.orders or []):
        parts.append(t("admission_results.labs_pending", lang))

    studies: list[str] = []
    for study in ctx.imaging_studies or []:
        report = _o(study, "report", None) or {}
        issued = recorded_by([report], as_of, "issued_datetime")
        impression = _o(report, f"impression_text_{lang}", None) or _o(report, "impression_text", None) or ""
        if not issued or not impression:
            continue
        name = imaging_exam_display(str(_o(study, "description", "") or ""), lang)
        studies.append(
            t("admission_results.imaging_item", lang, name=name, impression=str(impression).strip().rstrip("。."))
            if name
            else str(impression).strip()
        )
    if studies:
        facts.append("ctx.imaging_studies.known_at_note_time")
        parts.append(t("admission_results.imaging", lang, list=sep.join(studies)))

    if not parts:
        return t("admission_results.none_yet", lang), facts
    return t("list_sep.period_space", lang).join(parts), facts


@section("admission_summary")
def build_admission_summary(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build admission_summary for DISCHARGE_SUMMARY."""
    facts: list[str] = []
    lang = ctx.target_lang

    cc_text, cc_facts = section_builder("chief_complaint")(generator, ctx)
    facts.extend(cc_facts)

    text = t("admission_summary.head_line", lang, cc=cc_text, day=ctx.day_index + 1)

    return text, facts
