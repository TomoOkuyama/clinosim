"""hpi (History of Present Illness) section builder.

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1o of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

Three HPI-cluster helpers close with the builder and move alongside —
all grep-verified to have no callers outside the HPI cluster:
  - ``_build_hpi_core`` — core HPI content (pre-neonatal-append)
  - ``_maybe_append_newborn_workup`` — Issue #1432 neonatal addendum
  - ``_compose_hpi_extras_from_state`` — Issue #984 CIF-anchored
    enrichment (demographics + CC + chronic + meds + prior-care +
    ROS pertinent negatives)

Generator-threaded helper:
  - ``generator._get_ed_note_template`` (ED_NOTE path layer 2 — stays
    on the class because other ED builders also use it)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clinosim.codes import display as registry_display
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._narrative_utils import _age_at
from clinosim.modules.document.narrative._template_helpers import (
    _hpi_onset_en,
    _pick_localized,
    _render_home_med_name,
)
from clinosim.modules.document.reference_data_loaders import load_hpi_pertinent_negatives
from clinosim.types.document import DocumentType, NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


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
    terminator = "。" if ctx.target_lang == "ja" else "."
    appended = f"{summary}{terminator}"
    if text:
        joined = f"{text} {appended}"
    else:
        joined = appended
    facts.append("ctx.newborn_workup")
    return joined, facts


def _build_hpi_core(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """HPI content, pre-neonatal-append. See :func:`build_hpi`."""
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
    if sev and lang == "ja":
        from clinosim.modules.document.narrative.replacement_strategy import (
            _localize_severity_ja,
        )

        sev = _localize_severity_ja(sev)
    if sev:
        fallback = t("hpi_core.fallback_with_severity", lang, sev=sev)
    else:
        fallback = t("hpi_core.fallback_no_severity", lang)

    # ED_NOTE reads from ed_note_template
    if ctx.document_type == DocumentType.ED_NOTE:
        ed_tmpl = generator._get_ed_note_template(ctx)
        if ed_tmpl is not None:
            text = _pick_localized(ed_tmpl, "hpi", lang, ctx)
            if text:
                facts.append(f"encounter_protocol.narrative.ed_note_template.hpi_{lang}")
                # Issue #984: append CIF-anchored HPI extras (age/sex,
                # home meds, chronic list, ROS pertinent-negatives)
                # to the ED_NOTE onset seed. Before #984 the ED HPI
                # was a single-clause line (median 23 chars); the
                # extras extend it to real-EHR admission-note richness.
                extras = _compose_hpi_extras_from_state(ctx)
                if extras:
                    facts.extend(
                        [
                            "ctx.patient.demographics",
                            "ctx.patient.chronic_conditions",
                            "ctx.patient.current_medications",
                        ]
                    )
                    return f"{text} {extras}".strip(), facts
                return text, facts
        return fallback, facts

    proto = ctx.disease_protocol
    narrative = _o(proto, "narrative", None) if proto is not None else None
    if narrative is None:
        # v9 (2026-08-17) density: still append CIF-derived context
        # so HPI carries real patient data even for chronic-follow-up
        # encounters whose disease YAML has no narrative section.
        extras = _compose_hpi_extras_from_state(ctx)
        if extras:
            facts.extend(
                ["ctx.patient.demographics", "ctx.encounter.chief_complaint", "ctx.patient.chronic_conditions"]
            )
            return f"{fallback} {extras}".strip(), facts
        return fallback, facts

    hpi_tmpl = _o(narrative, "hpi_template", None)
    if hpi_tmpl is None:
        extras = _compose_hpi_extras_from_state(ctx)
        if extras:
            facts.extend(
                ["ctx.patient.demographics", "ctx.encounter.chief_complaint", "ctx.patient.chronic_conditions"]
            )
            return f"{fallback} {extras}".strip(), facts
        return fallback, facts

    # US-locale leak fix. `hpi_template.onset_pattern` and
    # `trigger_options` in disease YAMLs are JP-only strings. The EN
    # locale previously emitted the JP text (tagged
    # `:ja_only_fallback`), which surfaced as CJK in US Composition
    # `.section[].text.div`. The EN locale now synthesizes a
    # locale-neutral English phrase per severity and skips
    # `trigger_options` entirely (per-disease English wording is
    # deferred to the LLM narrative pass — a functional fallback beats
    # a locale leak).
    if lang != "ja":
        onset_text_en = _hpi_onset_en(ctx.severity)
        facts.append(f"generic:hpi_onset_en.{ctx.severity}")
        return onset_text_en, facts

    onset_pattern = _o(hpi_tmpl, "onset_pattern", {})
    if isinstance(onset_pattern, dict):
        onset_text = onset_pattern.get(ctx.severity) or onset_pattern.get("moderate") or ""
    else:
        onset_text = ""

    trigger_options = _o(hpi_tmpl, "trigger_options", []) or []
    trigger = trigger_options[0] if trigger_options else ""

    if onset_text:
        base = f"{onset_text} {trigger}".strip() if trigger else onset_text
        facts.append(f"disease_protocol.narrative.hpi_template.onset_pattern.{ctx.severity}")
        if trigger:
            facts.append("disease_protocol.narrative.hpi_template.trigger_options[0]")
    else:
        base = fallback

    # v9 (2026-08-17) density fix: append CIF-derived context
    # (demographics + chief_complaint + chronic overview) so HPI
    # carries per-patient specificity even when the disease YAML
    # onset_pattern is a short generic line.
    extras = _compose_hpi_extras_from_state(ctx)
    text = f"{base} {extras}".strip() if extras else base
    if extras:
        facts.extend(["ctx.patient.demographics", "ctx.encounter.chief_complaint", "ctx.patient.chronic_conditions"])

    return text, facts


def _compose_hpi_extras_from_state(ctx: NarrativeContext) -> str:
    """Append CIF-anchored HPI enrichment (Issue #984).

    Extends the disease-YAML onset_pattern seed with:
      - demographics: age + sex
      - chief_complaint from ``ctx.encounter``
      - chronic short list (top 3)
      - home meds reconciliation (up to top 3 current_medications)
      - prior-care attempt sentinel (derived from chronic + med presence,
        never fabricated as a specific institution or datetime)
      - ROS pertinent negatives from per-disease yaml pool

    Previously (v9) emitted only demographics + CC + chronic and hit a
    median 23 chars. #984 lifts median to ~100-150 chars while staying
    template-only (no LLM dependency) and CIF-anchored (no fabrication)."""
    if ctx.target_lang != "ja":
        return ""
    patient = ctx.patient
    enc = ctx.encounter
    parts: list[str] = []
    age = _age_at(ctx) if patient else None
    sex = _o(patient, "sex", None) if patient else ""
    # This branch only fires for JA output (early return above), so
    # we pin lang=ja for the yaml lookup. hardcoded-review Phase A15.
    sex_label = t(f"patient_demographics.sex_display.{str(sex).lower()}", "ja") if sex else ""
    # When the lookup misses (unknown sex code), t() falls through to
    # the raw key, which we don't want in the preamble. Treat a
    # dotted-key passthrough as empty so the age-only branch fires.
    if "." in sex_label:
        sex_label = ""
    if age and sex_label:
        parts.append(t("patient_demographics.patient_preamble_with_sex", "ja", age=age, sex=sex_label))
    elif age:
        parts.append(t("patient_demographics.patient_preamble_age_only", "ja", age=age))
    # chief_complaint from encounter (真の CIF、v9 bug fix)
    cc = ""
    if enc is not None:
        cc = _o(enc, "chief_complaint_ja", None) or _o(enc, "chief_complaint", None) or ""
    if cc:
        parts.append(f"主訴: {cc}。")
    # Chronic short list — Issue #1333: route CIF base code through
    # map_diagnosis_code so display matches the FHIR emit-target.
    from clinosim.modules.output.fhir_r4.lib.common import (
        map_diagnosis_code as _map_diagnosis_code,
    )

    country = "JP" if ctx.locale.lower() == "jp" else "US"
    conds = _o(patient, "chronic_conditions", []) or []
    chronic_labels: list[str] = []
    for c in conds[:3]:
        code = _o(c, "code", "") or (c if isinstance(c, str) else "")
        if not code:
            continue
        emit_code = _map_diagnosis_code(code, country) or code
        key = "icd-10" if ctx.locale == "jp" else "icd-10-cm"
        disp = registry_display(key, emit_code, ctx.target_lang) or emit_code
        chronic_labels.append(disp)
    if chronic_labels:
        parts.append(f"既往: {'、'.join(chronic_labels)}。")

    # Issue #984: home meds reconciliation (top 3 to keep HPI compact).
    # CIF-anchored — omitted when current_medications is empty; never
    # fabricated. Reuses _render_home_med_name so JA katakana localization
    # matches the medications_at_home section.
    meds = _o(patient, "current_medications", []) or []
    if meds:
        med_labels: list[str] = []
        for m in meds[:3]:
            name = _render_home_med_name(m, lang="ja")
            if name:
                med_labels.append(name)
        if med_labels:
            more = f"他 {len(meds) - len(med_labels)} 剤" if len(meds) > len(med_labels) else ""
            joined = "、".join(med_labels) + (f"、{more}" if more else "")
            parts.append(f"常用薬: {joined}。")

    # Issue #984: prior-care sentinel (derived — never claim a specific
    # institution or datetime not in CIF). Two branches:
    #   (a) patient has chronic conditions + current_medications → "かかりつけ医
    #       で処方継続中" (evidence: patient is under ongoing care)
    #   (b) neither → omit (silent no-op)
    if conds and meds:
        parts.append("かかりつけ医で内服治療継続中。")
    elif meds:
        parts.append("外来にて内服処方継続中。")

    # Issue #984: ROS pertinent negatives from per-disease yaml pool.
    # Reads the FIRST-listed 2 negatives to keep HPI length realistic.
    # Fallback (no disease_id / not in yaml) → omit rather than fabricate.
    disease_id = ""
    if ctx.disease_protocol is not None:
        disease_id = str(_o(ctx.disease_protocol, "disease_id", "") or "")
    if disease_id:
        neg_pool = load_hpi_pertinent_negatives().get(disease_id) or []
        if neg_pool:
            # Use up to 2 to keep HPI compact.
            selected = neg_pool[:2]
            parts.append(f"ROS: {'、'.join(selected)}。")

    return "".join(parts)
