"""ED_NOTE section builders — triage_details / ed_physical_exam /
ed_workup / ed_disposition.

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1j of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

Each builder is a free-standing ``(generator, ctx) -> (text, facts)``
function. The class methods of the same name become thin delegators so
``renderers/composition_sections.py`` (which looks up
``generator._build_<section>`` by name) stays unchanged.

Generator-threaded helpers:
  - ``generator._get_ed_note_template``
  - ``generator._compose_vital_signs_line``
  - ``generator._apply_cc_pe_consistency``
  - ``generator._compose_pe_vitals_line``
  - ``generator._ed_disposition_reason``
  - ``generator._ed_triage_level``
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from clinosim.codes import display
from clinosim.codes.ucum import ucum_prose
from clinosim.countries import has_authored_narrative
from clinosim.locale.i18n import t
from clinosim.locale.loader import lab_display
from clinosim.locale.loader import narrative_label as _label
from clinosim.locale.localized import language_slot, localized, normalize_lang
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._localization import (
    _localize_imaging,
    _localize_lab_flag,
)
from clinosim.modules.document.narrative._narrative_utils import _age_months_at
from clinosim.modules.document.narrative._template_helpers import (
    _GENERIC_FALLBACK_EN,
    _GENERIC_FALLBACK_JA,
    _fill_template_placeholders,
    _pick_localized,
)
from clinosim.modules.document.narrative.renderers.section_builders._registry import section, section_builder
from clinosim.modules.encounter.protocol import discharge_instructions_for_age
from clinosim.types.document import DocumentType, NarrativeContext

# An ED note rendered on an inpatient record is the ED part of a via-ED
# admission (the ED-companion stub, Issue #2856): its encounter is the stay.
_STAY_TYPES = frozenset({"inpatient", "icu", "rehab_inpatient"})


def _iso(value: object) -> str:
    return str(value or "").replace(" ", "T")[:19]


def _admitted_from_ed(ctx: NarrativeContext) -> bool:
    """True when this ED note belongs to a visit that ended in admission."""
    enc = ctx.encounter
    if enc is None:
        return False
    raw = _o(enc, "encounter_type", "") or ""
    enc_type = str(getattr(raw, "value", raw)).lower()
    return enc_type in _STAY_TYPES


def _ed_cutoff(ctx: NarrativeContext) -> str:
    """ISO time at which the ED part ended (the admission time) for an
    admitted patient, else ``""`` (no cutoff)."""
    if not _admitted_from_ed(ctx):
        return ""
    return _iso(_o(ctx.encounter, "admission_datetime", ""))


if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )

logger = logging.getLogger(__name__)


@section("triage_details")
def build_triage_details(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build triage_details from encounter.triage_data."""
    facts: list[str] = []
    lang = ctx.target_lang
    fallback = t("fallback.triage_fallback", lang)

    triage = _o(ctx.encounter, "triage_data", None)
    if triage is None:
        return fallback, facts

    facts.append("encounter.triage_data")
    level = _o(triage, "level", "") or ""
    level_system = _o(triage, "level_system", "") or ""
    arrival_mode = _o(triage, "arrival_mode", "") or ""
    arrival_display = _label("arrival_mode", arrival_mode, lang, fallback=arrival_mode)

    if level_system and level:
        level_text = t("triage_details.system_level", lang, system=level_system, level=level)
    else:
        level_text = t("control_status.not_assessed", lang)

    mode_display = arrival_display or t("triage_details.arrival_unknown", lang)
    return t("triage_details.line", lang, level=level_text, mode=mode_display), facts


@section("physical_exam")
def build_ed_physical_exam(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build physical_exam for ED_NOTE from ed_note_template.physical_exam_<lang>.

    v9 (2026-08-17) density fix — when encounter_protocol has no
    ed_note_template.physical_exam, fall back to arrival vitals +
    chief_complaint context rather than emitting a bare
    "特記事項なし".
    """
    facts: list[str] = []
    lang = ctx.target_lang
    fallback = t("fallback.generic_fallback", lang)

    ed_tmpl = generator._get_ed_note_template(ctx)
    if ed_tmpl is None:
        # v9 density: assemble from arrival vitals + severity
        vital_line = generator._compose_vital_signs_line(ctx)
        if vital_line:
            facts.append("ctx.vitals[0]")
            return t("ed.on_arrival_no_findings", lang, vitals=vital_line), facts
        return fallback, facts

    # physical_exam maps a language to a structured per-body-system object,
    # not a plain string, so it is resolved inline rather than via
    # _pick_localized (which coerces its result to str); same routing.
    field = "physical_exam"
    exams = _o(ed_tmpl, field, None) or {}
    # The findings in exactly the requested language (Issue #2507).
    pe = exams.get(normalize_lang(lang)) if isinstance(exams, dict) else None
    if pe is None:
        logger.warning("template field %s.%s missing on %s", field, lang, type(ed_tmpl).__name__)
        return fallback, facts

    # Collect non-empty body system findings (placeholder-substituted —
    # encounter YAML physical_exam_<lang> strings carry {severity_desc_*}
    # etc.; β-JP-1 chain 1a, same policy as _pick_localized). adv-1 I-2:
    # a part whose unknown placeholders collapsed it to the generic phrase
    # carries no information and would repeat per body system — drop it;
    # if every part collapses, the section-level fallback below fires once.
    systems = ("general", "cardiovascular", "respiratory", "abdominal", "neurological", "psychiatric")
    parts = []
    for sys_key in systems:
        val = _o(pe, sys_key, "") or ""
        if val:
            filled = _fill_template_placeholders(str(val), ctx, lang)
            if filled and filled != fallback:
                parts.append(filled)

    if parts:
        facts.append(f"encounter_protocol.narrative.ed_note_template.{field}_{lang}")  # provenance label as before
        sep = t("list_sep.period_space", lang)
        text = sep.join(parts)
        # JA-locale narrative enhancements (Issues #980 + #979). Both
        # are JA-specific by design: the rewrite pools + trigger
        # keywords in _apply_cc_pe_consistency are JP terminology,
        # and the vitals-line prepend is an inpatient-JA convention
        # not yet mirrored elsewhere. Adding a new locale (fr / zh)
        # would need its own contradiction-rewrite pool and
        # vitals-line style — this is a locale-specific data pipeline
        # gate, not a display translation.
        if has_authored_narrative(lang):
            text, cc_facts = generator._apply_cc_pe_consistency(text, ctx)
            facts.extend(cc_facts)
            vitals_line = generator._compose_pe_vitals_line(ctx)
            if vitals_line:
                facts.append(f"ctx.vitals[day_{ctx.day_index}]")
                text = t("ed_physical_exam.vitals_prepend", lang, vitals=vitals_line, text=text)
        return text, facts

    return fallback, facts


@section("ed_workup")
def build_ed_workup(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build ed_workup from ed_note_template.ed_workup_summary_<lang>.

    v9 (2026-08-17) density fix — assemble labs + procedures actually
    performed in ED when the encounter YAML has no ed_workup_summary
    template.

    Issue #981 density fix — before falling back to the abnormal-labs
    + procedures-only enumeration (which produced 71% "特記事項なし"
    placeholders in the p=2000 audit because ED encounters rarely
    have flagged lab_results at narrative time), enumerate the orders
    placed during the ED visit: lab test panel names + imaging
    modalities. Orders are the correct source for "what workup was
    run" — lab_results only surface `flag`-annotated abnormals,
    procedures only surface bedside interventions.
    """
    facts: list[str] = []
    lang = ctx.target_lang
    fallback = t("fallback.ed_workup_fallback", lang)

    ed_tmpl = generator._get_ed_note_template(ctx)
    if ed_tmpl is not None:
        text = _pick_localized(ed_tmpl, "ed_workup_summary", lang, ctx)
        # Issue #981: the ed_note_template values typically contain
        # unresolved substitution placeholders (`{lab_summary_ja}` etc.
        # from the minor-condition ED protocol templates). _pick_localized
        # returns the generic "特記事項なし" phrase in that case, which
        # short-circuited the fall-through to the CIF-driven enumeration
        # below. Treat the generic phrase (and the ED-specific fallback
        # phrase) as "no real template text" and fall through so the
        # orders / procedures / labs section can render instead.
        if text and text not in {_GENERIC_FALLBACK_JA, _GENERIC_FALLBACK_EN, fallback}:
            facts.append(f"encounter_protocol.narrative.ed_note_template.ed_workup_summary_{lang}")
            return text, facts

    # Issue #981 preferred fallback: lift the ED orders (labs / imaging
    # / medications / procedures) placed during this encounter into
    # the narrative. Orders are the accurate answer to "what did we
    # do in the ED"; the pre-#981 abnormal-labs-only path missed the
    # most common cases (blood draw ordered, results normal → labs
    # list empty; laceration repaired with procedure-only orders and
    # no lab_results at all).
    lab_names: list[str] = []
    imaging_names: list[str] = []
    med_names: list[str] = []
    proc_order_names: list[str] = []
    enc_id = _o(ctx.encounter, "encounter_id", "") if ctx.encounter is not None else ""
    seen_labs: set[str] = set()  # panel-key or display-name dedup
    seen_imaging: set[str] = set()
    seen_meds: set[str] = set()
    seen_proc_orders: set[str] = set()
    # The initial workup of a via-ED admission is placed as the stay's
    # admission orders, so the order list is kept; only result values are
    # limited to those available at the ED departure (Issue #2856).
    cutoff = _ed_cutoff(ctx)
    for order in ctx.orders or []:
        # Scope to the ED encounter only — record.orders can include a
        # follow-up outpatient order carried on the same patient file
        # in richer CIF layouts.
        if enc_id:
            oe = _o(order, "encounter_id", "") or ""
            if oe and oe != enc_id:
                continue
        otype = _o(order, "order_type", "") or ""
        otype_str = str(otype.value if hasattr(otype, "value") else otype).lower()
        display_raw = _o(order, "display_name", "") or _o(order, "order_code", "")
        if otype_str == "lab":
            key = _o(order, "panel_key", "") or display_raw
            display = _o(order, "panel_key", "") or display_raw
            if key and str(key) not in seen_labs:
                seen_labs.add(str(key))
                lab_names.append(str(display))
        elif otype_str == "imaging":
            modality = str(_o(order, "imaging_modality", "") or "").upper()
            display = display_raw or modality
            key = f"{modality}|{display}"
            if display and key not in seen_imaging:
                seen_imaging.add(key)
                imaging_names.append(str(display))
        elif otype_str == "medication":
            if display_raw and str(display_raw) not in seen_meds:
                seen_meds.add(str(display_raw))
                med_names.append(str(display_raw))
        elif otype_str == "procedure":
            if display_raw and str(display_raw) not in seen_proc_orders:
                seen_proc_orders.add(str(display_raw))
                proc_order_names.append(str(display_raw))
    parts: list[str] = []
    if lab_names:
        # Phase 1c-4 (2026-09-23): localise lab / panel tokens
        # ("Creatinine" / "CBC" / "Urinalysis" / "Total_bilirubin"
        # etc.) via ``lab_display``. Pre-fix, the JA emission
        # embedded English tokens verbatim under 「検査:」.
        lab_names_disp = [lab_display(n, ctx.target_lang) for n in lab_names[:8]]
        parts.append(t("ed_workup.labs_head", lang) + t("list_sep.serial", lang).join(lab_names_disp))
    if imaging_names:
        # Phase 1c-4 (2026-09-23): localise imaging codes
        # ("Chest_Xray_PA_Lateral" / "CT_Head" / etc.) via
        # ``_localize_imaging``. Handles both underscore-slug and
        # spaced-name variants (semantic dedup).
        imaging_display = [_localize_imaging(n, ctx.target_lang) for n in imaging_names[:6]]
        parts.append(t("ed_workup.imaging_head", lang) + t("list_sep.serial", lang).join(imaging_display))
    if med_names:
        # Phase 1c-3 (2026-09-22): localize med display names to
        # katakana JA via the shared `load_narrative_display_dict` catalog used by
        # the FHIR emit path. Pre-fix 183 JP ed_workup lines carried
        # 「投薬: Ibuprofen 400mg、Acetaminophen 500mg」 verbatim.
        med_display = med_names[:6]
        # Drug-name katakana lookup via lang-aware wrapper (no-op
        # for lang without a lookup table). Broad except keeps a
        # narrative render from failing on an i18n edge case.
        try:
            from clinosim.locale.free_text import localize_drug_name

            med_display = [localize_drug_name(m, lang) or m for m in med_display]
        except Exception:  # noqa: BLE001 — never fail narrative on i18n
            pass
        parts.append(t("ed_workup.medications_head", lang) + t("list_sep.serial", lang).join(med_display))
    if proc_order_names:
        # Phase 1c-6 (Category L, 2026-09-23): route each procedure
        # order display name through ``_localize_drug_name`` (which
        # also invokes ``_localize_dosage_terms`` internally) on JA
        # output so composite English phrases like
        # 「bronchodilator: Salbutamol 2.5mg nebulizer q4h」 →
        # 「気管支拡張薬: サルブタモール 2.5mg ネブライザー 4時間毎」.
        # Pre-fix ~1,700 leaks in the JP p=10000 audit across
        # bronchodilator / nebulizer / cannula / irrigation /
        # bandage / saline / Salbutamol / Ipratropium / etc. Lazy
        # import + broad except mirrors the med_display handler.
        proc_display = proc_order_names[:6]
        # Drug/procedure display katakana via lang-aware wrapper
        # (same wrapper as med_display above).
        try:
            from clinosim.locale.free_text import localize_procedure_name

            proc_display = [localize_procedure_name(p, lang) or p for p in proc_display]
        except Exception:  # noqa: BLE001
            pass
        parts.append(t("ed_workup.procedures_ordered_head", lang) + t("list_sep.serial", lang).join(proc_display))

    # Enrich with any flagged abnormals (kept from the v9 path — an
    # abnormal Cr / K reading is high-signal even when the panel it
    # came from is already listed above).
    #
    # Phase 1c-5 (2026-09-23): sibling of the progress_note
    # ``本日の検査所見:`` fix — route lab_name through
    # ``lab_display`` and flag through ``_localize_lab_flag``
    # so JA emits 「クレアチニン 5.19 mg/dL [H]、BUN 143.8 mg/dL [H]」
    # rather than 「Creatinine 5.19 mg/dL [H]、BUN 143.8 mg/dL [H]」.
    # Pre-fix the JP p=10000 audit surfaced ~2,000 raw-English lab
    # names in ed_workup ``異常値:`` lines (Creatinine / Albumin /
    # Glucose / Lactate / Troponin_I / …).
    abn_labs = []
    ed_labs = [
        lab
        for lab in (ctx.lab_results or [])
        if not cutoff or (_iso(_o(lab, "result_datetime", "")) and _iso(_o(lab, "result_datetime", "")) <= cutoff)
    ]
    for lab in ed_labs[:8]:
        flag = _o(lab, "flag", None)
        if not flag:
            continue
        name = _o(lab, "lab_name", "") or ""
        val = _o(lab, "value", None)
        unit = _o(lab, "unit", "") or ""
        if name and val is not None:
            disp_name = lab_display(name, ctx.target_lang)
            disp_flag = _localize_lab_flag(flag, ctx.target_lang)
            unit_disp = ucum_prose(unit)
            # Phase 1d-81 follow-up: same unit=name dedupe as
            # Phase 1d-80 covered in the two progress_note sites;
            # this ed_workup abnormal-lab emit needs it too. Real
            # case: pH lab (`lab_name="pH"` / `unit="[pH]"`) →
            # `pH 7.33 pH [L]` visible dup.
            if unit_disp and unit_disp.lower() == str(disp_name).lower():
                unit_disp = ""
            unit_part = f" {unit_disp}" if unit_disp else ""
            abn_labs.append(f"{disp_name} {val}{unit_part} [{disp_flag}]")
    if abn_labs:
        parts.append(t("ed_workup.abnormal_head", lang) + t("list_sep.serial", lang).join(abn_labs[:4]))

    # Bedside procedures / imaging descriptions.
    procs = []
    for pr in (ctx.procedures or [])[:4]:
        nm = _o(pr, "procedure_name", None) or _o(pr, "name", None)
        if nm:
            procs.append(str(nm))
    if procs:
        parts.append(t("ed_workup.procedures_head", lang) + t("list_sep.serial", lang).join(procs))
    if parts:
        fact_sources = []
        if lab_names or imaging_names or med_names or proc_order_names:
            fact_sources.append("ctx.orders.ed")
        if abn_labs:
            fact_sources.append("ctx.lab_results.abnormal")
        if procs:
            fact_sources.append("ctx.procedures.ed")
        facts.extend(fact_sources)
        return t("list_sep.period_space", lang).join(parts), facts

    return fallback, facts


@section("disposition")
def build_ed_disposition(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build disposition from ed_note_template.disposition_<lang>.

    v9 (2026-08-17) density fix — infer disposition from encounter
    outcome (discharge_disposition / admission linkage) when
    ed_note_template is absent, rather than emitting a bare
    "帰宅または入院加療".

    Issue #981 density fix — attach a reasoning phrase drawn from
    the admit-diagnosis / disease_protocol / acuity so every
    disposition sentence reads as "自宅退院（JTAS レベル 4、症状軽度）"
    instead of the bare "自宅退院。症状経過に応じて再受診指示。" that
    the pre-#981 code produced (68% of ED docs).
    """
    facts: list[str] = []
    lang = ctx.target_lang
    fallback = t("fallback.disposition_fallback", lang)

    outcome, base = _encounter_disposition(generator, ctx, lang)
    if outcome:
        facts.append("ctx.encounter.disposition")
    if outcome and outcome != "home":
        # Admission / transfer / death: the outcome line alone (Issue #2856);
        # the protocol's template and instructions are written for a patient
        # sent home.
        return base, facts

    text = base
    ed_tmpl = generator._get_ed_note_template(ctx)
    if ed_tmpl is not None:
        # The protocol's disposition template wraps the outcome line
        # (`{disposition_display_<lang>}`) in its own clinical wording.
        raw = language_slot(_o(ed_tmpl, "disposition", None), lang)
        extra = {f"disposition_display_{lang}": base} if base else None
        filled = _fill_template_placeholders(raw, ctx, lang, extra=extra) if raw else ""
        if filled and filled not in {_GENERIC_FALLBACK_JA, _GENERIC_FALLBACK_EN, fallback}:
            facts.append(f"encounter_protocol.narrative.ed_note_template.disposition_{lang}")
            text = filled
    if not text:
        return fallback, facts
    if outcome != "home":
        return text, facts

    parts = [text.rstrip(t("list_sep.period", lang)) + t("list_sep.period", lang)]
    proto = ctx.encounter_protocol
    # Issue #2980: an age-gated instruction (honey for cough) has a variant
    # for a younger patient.
    instructions = [localized(item, lang) for item in discharge_instructions_for_age(proto, _age_months_at(ctx))]
    instructions = [item for item in instructions if item]
    if instructions:
        sep = t("ed.instruction_sep", lang)
        parts.append(t("ed.discharge_instructions", lang, list=sep.join(instructions)))
        facts.append("encounter_protocol.discharge_instructions")
    follow_up = localized(_o(proto, "follow_up", None), lang) if proto is not None else ""
    if follow_up:
        parts.append(t("ed.follow_up", lang, text=follow_up))
        facts.append("encounter_protocol.follow_up")
    # The instruction / follow-up phrases carry their own leading separator.
    return "".join(parts), facts


def _encounter_disposition(generator: TemplateNarrativeGenerator, ctx: NarrativeContext, lang: str) -> tuple[str, str]:
    """``(outcome, line)`` of the ED visit from the encounter fields —
    ``outcome`` is ``admitted`` / ``expired`` / ``psychiatric`` /
    ``transfer`` / ``home``, or ``""`` (with ``line`` ``""``) when unknown.

    v9 density / Issue #981: the line carries a reasoning phrase drawn from
    the complaint / acuity ("Discharged home (ESI level 4, ...)").
    """
    enc = ctx.encounter
    if enc is None:
        return "", ""
    dispo = str(_o(enc, "discharge_disposition", None) or _o(enc, "outcome", None) or "").lower()
    adm = _o(enc, "admit_to_ward", None) or bool(_o(enc, "admitted", False))
    reason = generator._ed_disposition_reason(ctx, lang)

    # Issue #2856: on an admitted patient's record the encounter is the
    # stay, whose discharge disposition (home / exp) is not the ED's.
    # Deprecated `admit_to_ward` (legacy fixtures) is normalized to the same
    # "admitted" path as an inbound transfer disposition.
    if adm or dispo == "hosp" or _admitted_from_ed(ctx):
        return "admitted", t("fallback.ed_disposition_admission", lang).format(reason=reason)
    if dispo == "exp":
        return "expired", t("fallback.ed_disposition_expired", lang)
    if dispo == "psy":
        return "psychiatric", t("fallback.ed_disposition_psychiatric_transfer", lang).format(reason=reason)
    if dispo in ("other-hcf", "snf"):
        return "transfer", t("fallback.ed_disposition_transfer", lang).format(reason=reason)
    if dispo == "home":
        level = generator._ed_triage_level(ctx)
        return "home", t("fallback.ed_disposition_home", lang).format(level=level, reason=reason)
    return "", ""


@section("assessment", document_type=DocumentType.ED_NOTE)
def build_ed_assessment(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """ED assessment: the visit's diagnosis and chief complaint (Issue #2871).

    The diagnosis is the encounter's coded admission diagnosis (the ED
    diagnosis; for a via-ED admission, the admitting diagnosis), displayed in
    the note's language. Without one the shared assessment builder composes
    the section.
    """
    lang = ctx.target_lang
    dx = _ed_diagnosis_display(ctx, lang)
    if not dx:
        return section_builder("assessment")(generator, ctx)
    facts = ["ctx.diagnoses.admission_diagnosis_code"]
    enc = ctx.encounter
    cc = str(_o(enc, f"chief_complaint_{lang}", "") or _o(enc, "chief_complaint", "") or "").strip() if enc else ""
    if cc and cc.lower() != dx.lower():
        facts.append("ctx.encounter.chief_complaint")
        return t("ed.assessment_diagnosis", lang, dx=dx, cc=cc), facts
    return t("ed.assessment_diagnosis_only", lang, dx=dx), facts


def _ed_diagnosis_display(ctx: NarrativeContext, lang: str) -> str:
    """Display of the encounter's admission diagnosis code, or ``""``."""
    for diagnosis in ctx.diagnoses or []:
        code = str(_o(diagnosis, "admission_diagnosis_code", "") or "")
        system = str(_o(diagnosis, "admission_diagnosis_system", "") or "")
        if code and system:
            return display(system, code, lang) or ""
    return ""
