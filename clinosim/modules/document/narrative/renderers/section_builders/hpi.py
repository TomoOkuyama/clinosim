"""hpi (History of Present Illness) section builder.

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1o of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

Three HPI-cluster helpers close with the builder and move alongside —
all grep-verified to have no callers outside the HPI cluster:
  - ``_build_hpi_core`` — core HPI content (pre-neonatal-append)
  - ``_maybe_append_newborn_workup`` — Issue #1432 neonatal addendum
  - ``_hpi_parts`` / ``_ros_line`` —
    Issue #984 CIF-anchored enrichment (demographics + CC + chronic + meds
    + prior-care + ROS pertinent negatives), ordered around one onset
    sentence (``_onset_sentence``, Issue #3228)

Generator-threaded helper:
  - ``generator._get_ed_note_template`` (ED_NOTE path layer 2 — stays
    on the class because other ED builders also use it)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from clinosim.countries import country_code, has_authored_narrative
from clinosim.locale.i18n import t
from clinosim.locale.localized import localized_field
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._narrative_utils import _age_at, _cc_keyword_positively_present
from clinosim.modules.document.narrative._template_helpers import (
    _hpi_onset,
    _pick_localized,
    _render_home_med_name,
)
from clinosim.modules.document.narrative.renderers.section_builders._registry import section
from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
    home_medications_at_admission,
)
from clinosim.modules.document.reference_data_loaders import hpi_pertinent_negatives
from clinosim.types.document import DocumentType, NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


@section("hpi")
def build_hpi(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build HPI section, then append the neonatal workup one-liner
    for birth admissions (Issue #1432).

    The core HPI builder has multiple return paths (ED_NOTE branch,
    no-narrative fallback, missing-hpi_template fallback, EN locale
    onset synthesis, JA onset_pattern) — wrapping the whole thing so
    every path picks up the newborn workup append without duplicating
    the check at each return.
    """
    text, facts = _build_hpi_core(generator, ctx)
    return _maybe_append_newborn_workup(text, facts, ctx)


def _maybe_append_newborn_workup(text: str, facts: list[str], ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Issue #1432: append the newborn workup one-liner to HPI when
    ``ctx.newborn_workup["is_neonate"]`` is true and the rendered
    summary is non-empty. The summary is built by
    ``replacement_strategy._render_newborn_workup_summary`` — the
    same helper the LLM prompt grounding uses, so template body and
    LLM narrative anchor on identical CIF-derived facts.
    """
    workup = getattr(ctx, "newborn_workup", None) or {}
    if not workup.get("is_neonate"):
        return text, facts
    from clinosim.modules.document.narrative.replacement_strategy import (
        _render_newborn_workup_summary,
    )

    summary = _render_newborn_workup_summary(workup, lang=ctx.target_lang)
    if not summary:
        return text, facts
    # Terminate the appended fragment with the locale-appropriate
    # sentence punctuation so the section reads as one paragraph.
    terminator = t("punct.sentence_end", ctx.target_lang)
    appended = f"{summary}{terminator}"
    if text:
        joined = f"{text} {appended}"
    else:
        joined = appended
    facts.append("ctx.newborn_workup")
    return joined, facts


def _build_hpi_core(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """HPI content, pre-neonatal-append. See :func:`build_hpi`.

    Issue #3228: the parts are written in one order — demographics and chief
    complaint, then one onset sentence (the disease's authored onset, else the
    generic sentence of its ``onset_type``) with its trigger clause, then
    history, home medications and the pertinent negatives that do not deny a
    symptom of the complaint or the onset text. The ``受診となった。`` seed is
    written only when nothing else is.
    """
    facts: list[str] = []
    lang = ctx.target_lang
    # JA: localize severity token (mild/moderate/... → 軽度/中等度/...)
    # so the LLM doesn't inherit the EN token into its output — same
    # rule as `_build_admission_hp_condition` line ~1393. EN branch
    # keeps the raw token because it is already valid English.
    # #1266: guard against empty ctx.severity — for records with no
    # graded severity (e.g. newborn Z38.0 US, 28.5 % of admissions at
    # s=351 p=10k) the raw f-string interpolated `""` producing the
    # doubled-space fingerprint "Patient presented with  symptoms."
    # in the emitted Composition. Both locales use the natural
    # chief-complaint-less form on empty severity.
    sev = str(ctx.severity or "").strip()
    from clinosim.modules.document.narrative._replacement_localization import localize_token

    sev = localize_token(sev, "severity", lang)
    # Issue #3228: without a severity the seed says only "presented"; it is
    # written only when no other HPI content follows (else it opens the HPI
    # as a bare fragment, e.g. a newborn's "受診となった。 主訴: …").
    fallback = t("hpi_core.fallback_with_severity", lang, sev=sev) if sev else ""
    presented = t("hpi_core.fallback_no_severity", lang)

    # ED_NOTE reads from ed_note_template
    if ctx.document_type == DocumentType.ED_NOTE:
        ed_tmpl = generator._get_ed_note_template(ctx)
        if ed_tmpl is not None:
            text = _pick_localized(ed_tmpl, "hpi", lang, ctx)
            if text:
                facts.append(f"encounter_protocol.narrative.ed_note_template.hpi_{lang}")
                # Issue #984: CIF-anchored HPI extras (age/sex, chronic list,
                # home meds, ROS pertinent negatives) extend the ED onset seed.
                # Issue #3228: the authored seed already describes the
                # complaint, so the chief complaint is not restated after it;
                # the demographics open the HPI.
                parts = _hpi_parts(ctx)
                if parts.demographics or parts.details or _ros_line(ctx, f"{parts.chief_complaint}{text}"):
                    facts.extend(["ctx.patient.demographics", "ctx.patient.chronic_conditions"])
                    facts.append(home_medications_at_admission(ctx)[1])
                return _join(
                    parts.demographics, text, parts.details, _ros_line(ctx, f"{parts.chief_complaint}{text}")
                ), facts
        return fallback or presented, facts

    proto = ctx.disease_protocol
    narrative = _o(proto, "narrative", None) if proto is not None else None
    hpi_tmpl = _o(narrative, "hpi_template", None) if narrative is not None else None
    if hpi_tmpl is None:
        # v9 (2026-08-17) density: still append CIF-derived context
        # so HPI carries real patient data even for chronic-follow-up
        # encounters whose disease YAML has no narrative section.
        return _with_extras(ctx, fallback, presented, facts)

    # US-locale leak fix. `hpi_template.onset_pattern` and
    # `trigger_options` in disease YAMLs are JP-only strings. The EN
    # locale previously emitted the JP text (tagged
    # `:ja_only_fallback`), which surfaced as CJK in US Composition
    # `.section[].text.div`. The EN locale now synthesizes a
    # locale-neutral English phrase per severity and skips
    # `trigger_options` entirely (per-disease English wording is
    # deferred to the LLM narrative pass — a functional fallback beats
    # a locale leak).
    if not has_authored_narrative(lang):
        facts.append(f"generic:hpi_onset_en.{ctx.severity}")
        return _hpi_onset(ctx.severity, lang), facts

    onset = _onset_sentence(hpi_tmpl, ctx, facts)
    return _with_extras(ctx, onset or fallback, presented, facts)


def _onset_sentence(hpi_tmpl: object, ctx: NarrativeContext, facts: list[str]) -> str:
    """The one onset sentence of the HPI (Issue #3228): the disease's authored
    ``onset_pattern`` for the severity, else the generic sentence of its
    ``onset_type`` (``narrative_phrases.yaml::hpi.onset_by_type``), followed by
    the first trigger clause as its own sentence. ``""`` when neither exists."""
    lang = ctx.target_lang
    severity = str(ctx.severity or "")
    onset_pattern = _o(hpi_tmpl, "onset_pattern", {})
    onset_text = ""
    if isinstance(onset_pattern, dict):
        onset_text = onset_pattern.get(severity) or onset_pattern.get("moderate") or ""
    if onset_text:
        facts.append(f"disease_protocol.narrative.hpi_template.onset_pattern.{severity}")
    else:
        onset_type = _o(hpi_tmpl, "onset_type", None)
        if onset_type:
            onset_text = t(f"hpi.onset_by_type.{onset_type}.{severity}", lang) or t(
                f"hpi.onset_by_type.{onset_type}.moderate", lang
            )
            if onset_text:
                facts.append(f"disease_protocol.narrative.hpi_template.onset_type.{onset_type}")
    if not onset_text:
        return ""
    trigger_options = _o(hpi_tmpl, "trigger_options", []) or []
    trigger = str(trigger_options[0]).strip() if trigger_options else ""
    if trigger:
        facts.append("disease_protocol.narrative.hpi_template.trigger_options[0]")
        return f"{onset_text}{trigger}{t('punct.sentence_end', lang)}"
    return str(onset_text)


def _with_extras(ctx: NarrativeContext, onset: str, presented: str, facts: list[str]) -> tuple[str, list[str]]:
    """Demographics + chief complaint, the onset sentence, then history,
    home medications and the ROS line (Issue #3228 order). ``presented``
    (``受診となった。``) stands in only when the HPI would otherwise be empty."""
    parts = _hpi_parts(ctx)
    ros = _ros_line(ctx, f"{parts.chief_complaint}{onset}")
    if parts.demographics or parts.chief_complaint or parts.details or ros:
        facts.extend(["ctx.patient.demographics", "ctx.encounter.chief_complaint", "ctx.patient.chronic_conditions"])
    text = _join(parts.demographics, parts.chief_complaint, onset, parts.details, ros)
    return text or presented, facts


def _join(*sentences: str) -> str:
    """Concatenate HPI sentences (each already ends with its punctuation)."""
    return "".join(s.strip() for s in sentences if s and s.strip())


class _HpiParts(NamedTuple):
    """The CIF-anchored HPI sentences (Issue #984), kept apart so the caller
    can place the onset between the introduction and the details (#3228)."""

    demographics: str
    chief_complaint: str
    details: str  # history, home medications, prior-care sentence


def _hpi_parts(ctx: NarrativeContext) -> _HpiParts:
    """CIF-anchored HPI enrichment (Issue #984).

    Extends the disease-YAML onset_pattern seed with:
      - demographics: age + sex
      - chief_complaint from ``ctx.encounter``
      - chronic short list (top 3)
      - home meds reconciliation (up to top 3 of the medications taken
        when the encounter began, Issue #3262)
      - prior-care attempt sentinel (derived from chronic + med presence,
        never fabricated as a specific institution or datetime)

    The ROS pertinent negatives are written by :func:`_ros_line`, which needs
    the onset text as well. Template-only (no LLM dependency) and CIF-anchored
    (no fabrication)."""
    lang = ctx.target_lang
    if not has_authored_narrative(lang):
        return _HpiParts("", "", "")
    patient = ctx.patient
    enc = ctx.encounter
    demographics = ""
    age = _age_at(ctx) if patient else None
    sex = _o(patient, "sex", None) if patient else ""
    sex_label = t(f"patient_demographics.sex_display.{str(sex).lower()}", lang) if sex else ""
    # When the lookup misses (unknown sex code), t() falls through to
    # the raw key, which we don't want in the preamble. Treat a
    # dotted-key passthrough as empty so the age-only branch fires.
    if "." in sex_label:
        sex_label = ""
    if age and sex_label:
        demographics = t("patient_demographics.patient_preamble_with_sex", lang, age=age, sex=sex_label)
    elif age:
        demographics = t("patient_demographics.patient_preamble_age_only", lang, age=age)
    # chief_complaint from encounter (真の CIF、v9 bug fix)
    cc = ""
    if enc is not None:
        cc = localized_field(enc, "chief_complaint", lang)
    if cc:
        cc = _displayed_chief_complaint(cc, ctx)
    cc_sentence = t("narrative_text.hpi.chief_complaint", lang, cc=cc) if cc else ""
    parts: list[str] = []
    # Chronic short list — Issue #1333: route CIF base code through
    # map_diagnosis_code so display matches the FHIR emit-target.
    from clinosim.modules.document.narrative.renderers._shared_helpers import (
        chronic_condition_code,
        chronic_condition_label,
    )

    country = country_code(ctx.locale)
    conds = _o(patient, "chronic_conditions", []) or []
    chronic_labels: list[str] = []
    for c in conds[:3]:
        code = _o(c, "code", "") or (c if isinstance(c, str) else "")
        if not code:
            continue
        disp = chronic_condition_label(code, country, ctx.target_lang, str(_o(patient, "sex", "") or ""))
        chronic_labels.append(disp or chronic_condition_code(code, country))
    if chronic_labels:
        parts.append(
            t("narrative_text.hpi.history", lang, items=t("narrative_text.hpi.list_sep", lang).join(chronic_labels))
        )

    # Issue #984: home meds reconciliation (top 3 to keep HPI compact).
    # CIF-anchored — omitted when the patient took none; never fabricated.
    # Issue #3262: the medications when the encounter began (the record's
    # snapshot), not the end-of-simulation current_medications — the same
    # list the medications_at_home section reads. Reuses
    # _render_home_med_name so JA katakana localization matches it.
    meds, _ = home_medications_at_admission(ctx)
    if meds:
        med_labels: list[str] = []
        for m in meds[:3]:
            name = _render_home_med_name(m, lang=lang)
            if name:
                med_labels.append(name)
        if med_labels:
            sep = t("narrative_text.hpi.list_sep", lang)
            more = (
                t("narrative_text.hpi.more_meds", lang, n=len(meds) - len(med_labels))
                if len(meds) > len(med_labels)
                else ""
            )
            joined = sep.join(med_labels) + (f"{sep}{more}" if more else "")
            parts.append(t("narrative_text.hpi.home_meds", lang, items=joined))

    # Issue #984: prior-care sentinel (derived — never claim a specific
    # institution or datetime not in CIF). Two branches:
    #   (a) patient has chronic conditions + home medications → "かかりつけ医
    #       で処方継続中" (evidence: patient is under ongoing care)
    #   (b) neither → omit (silent no-op)
    if conds and meds:
        parts.append(t("narrative_text.hpi.prior_care_chronic", lang))
    elif meds:
        parts.append(t("narrative_text.hpi.prior_care_outpatient", lang))

    return _HpiParts(demographics, cc_sentence, "".join(parts))


def _displayed_chief_complaint(cc: str, ctx: NarrativeContext) -> str:
    """The chief complaint as the chief_complaint section writes it: a
    disease-default complaint is shown as the encounter's variant (Issue
    #983), so the HPI must name the same one (Issue #3228) — else the H&P
    carries two complaints and the ROS filter checks the wrong one."""
    from clinosim.modules.document.narrative.renderers.section_builders.chief_complaint import (
        _disease_canonical_cc,
        _maybe_swap_cc_variant,
    )

    disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol is not None else None
    condition_id = _o(ctx.encounter_protocol, "condition_id", None) if ctx.encounter_protocol is not None else None
    swapped, _ = _maybe_swap_cc_variant(
        cc,
        disease_id,
        _disease_canonical_cc(ctx.disease_protocol, ctx.target_lang),
        ctx.target_lang,
        ctx,
        encounter_condition_id=condition_id,
        canonical_encounter_cc=_disease_canonical_cc(ctx.encounter_protocol, ctx.target_lang),
    )
    return swapped


def _ros_line(ctx: NarrativeContext, presented_text: str) -> str:
    """The ROS pertinent negatives of the disease (Issue #984): the first two
    that do not deny a symptom positively present in ``presented_text`` (the
    chief complaint and onset text, Issue #3228) and are not already written
    there. ``""`` without a disease or negatives — never fabricated."""
    lang = ctx.target_lang
    if not has_authored_narrative(lang) or ctx.disease_protocol is None:
        return ""
    disease_id = str(_o(ctx.disease_protocol, "disease_id", "") or "")
    if not disease_id:
        return ""
    haystack = presented_text.lower()
    kept = [
        neg.text
        for neg in hpi_pertinent_negatives(disease_id, lang)
        if neg.text.lower() not in haystack
        and not _cc_keyword_positively_present(haystack, tuple(s.lower() for s in neg.symptoms))
    ]
    if not kept:
        return ""
    return t("narrative_text.hpi.ros", lang, items=t("narrative_text.hpi.list_sep", lang).join(kept[:2]))
