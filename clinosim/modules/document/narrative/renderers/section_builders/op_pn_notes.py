"""OPERATIVE_NOTE (LOINC 11504-8) + PROCEDURE_NOTE (LOINC 28570-0)
section builders.

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1d of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

Each builder is a free-standing ``(generator, ctx) -> (text, facts)``
function. The class methods of the same name become thin delegators so
``renderers/composition_sections.py`` (which looks up
``generator._build_<section>`` by name) stays unchanged.

OP builders delegate to ``generator._primary_surgical_procedure`` and
``generator._resolve_procedure_display`` for the shared surgical-
procedure resolution logic that stays on the class. PN builders carry
their own ``_pn_resolve_procedure`` helper (also moved here).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from clinosim.codes import lookup as code_lookup
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._localization import (
    _localize_complication,
    _localize_op_approach,
    _localize_op_implant,
    _localize_proc_type,
)
from clinosim.modules.document.narrative._template_helpers import _label, _resolve_staff_name
from clinosim.types.document import NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


# ─────────────────────────────────────────────────────────────────────
# OPERATIVE_NOTE (LOINC 11504-8) — surgical procedure note.
# ─────────────────────────────────────────────────────────────────────


def build_op_procedure_name(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """術式名 — procedure code display + K/CPT code + approach modifier."""
    lang = ctx.target_lang
    proc = generator._primary_surgical_procedure(ctx)
    if proc is None:
        return t("op_note.procedure_not_documented", lang), []
    facts = ["ctx.procedures"]
    name = generator._resolve_procedure_display(proc, lang)
    code = _o(proc, "procedure_code", "") or _o(proc, "procedure_code_jp", "") or _o(proc, "procedure_code_us", "")
    approach_raw = str(_o(proc, "approach", "") or "").lower()
    approach = _localize_op_approach(approach_raw, lang)
    duration = _o(proc, "duration_minutes", 0) or 0
    head = t("op_note.procedure_head", lang, name=name)
    approach_part = t("op_note.procedure_approach_paren", lang, approach=approach) if approach else ""
    code_part = t("op_note.procedure_code_paren", lang, code=code) if code else ""
    duration_part = t("op_note.procedure_duration_suffix", lang, duration=duration) if duration else ""
    return f"{head}{approach_part}{code_part}{duration_part}", facts


def build_op_anesthesia(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """麻酔法 — anesthesia type + ASA class + anesthesiologist."""
    lang = ctx.target_lang
    proc = generator._primary_surgical_procedure(ctx)
    if proc is None:
        return t("op_note.anesthesia_not_documented", lang), []
    facts = ["ctx.procedures"]
    atype = str(_o(proc, "anesthesia_type", "") or "").lower()
    # ``_OP_ANESTHESIA_JA/EN`` moved to
    # ``narrative_labels.yaml::op_anesthesia_type`` (Phase 1d-24).
    anes_label = _label("op_anesthesia_type", atype, lang, fallback=atype or t("op_note.anes_no_record", lang))
    asa = _o(proc, "asa_class", 0) or 0
    anes_id = _o(proc, "anesthesiologist_id", "") or ""
    anes_name = _resolve_staff_name(anes_id, ctx.roster_map) if anes_id else ""
    head = t("op_note.anesthesia_head", lang, label=anes_label)
    asa_part = t("op_note.anesthesia_asa_suffix", lang, asa=asa) if asa else ""
    anes_part = t("op_note.anesthesia_anesthesiologist_suffix", lang, name=anes_name) if anes_name else ""
    return f"{head}{asa_part}{anes_part}", facts


def build_op_surgeon(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """執刀医・助手 — primary surgeon + assistant list (name-resolved)."""
    lang = ctx.target_lang
    proc = generator._primary_surgical_procedure(ctx)
    if proc is None:
        return t("op_note.surgeon_not_documented", lang), []
    facts = ["ctx.procedures"]
    surgeon_id = _o(proc, "primary_surgeon_id", "") or ""
    surgeon_name = _resolve_staff_name(surgeon_id, ctx.roster_map) if surgeon_id else ""
    assistant_ids = list(_o(proc, "assistant_ids", []) or [])
    assistant_names = [_resolve_staff_name(a, ctx.roster_map) for a in assistant_ids if a]
    sep = t("list_sep.serial", lang)
    surgeon_part = (
        t("op_note.surgeon_line", lang, surgeon=surgeon_name) if surgeon_name else t("op_note.surgeon_none", lang)
    )
    assist_part = (
        t("op_note.assistants_suffix", lang, list=sep.join(assistant_names))
        if assistant_names
        else t("op_note.assistants_none_suffix", lang)
    )
    return f"{surgeon_part}{assist_part}", facts


def build_op_findings(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """術中所見 — body site + preop/postop diagnosis + intraop complications."""
    lang = ctx.target_lang
    proc = generator._primary_surgical_procedure(ctx)
    if proc is None:
        return t("op_note.findings_not_documented", lang), []
    facts = ["ctx.procedures"]
    body_site_code = _o(proc, "body_site_code", "") or ""
    # snomed-ct is the canonical system key (loader.py). Lookup returns
    # the code string itself when unresolved — treat that as "no display"
    # so we never leak raw SNOMED numeric codes into the narrative.
    body_site_disp = code_lookup("snomed-ct", body_site_code, lang) if body_site_code else ""
    body_site = body_site_disp if body_site_disp and body_site_disp != body_site_code else ""
    preop = _o(proc, "preop_diagnosis", "") or ""
    postop = _o(proc, "postop_diagnosis", "") or ""
    intraop = list(_o(proc, "intraop_complications", []) or [])
    # Phase 1c-6 (Category K, 2026-09-23): preop / postop diagnosis
    # are stamped with the disease_id slug (hip_fracture /
    # acute_cholecystitis / …) and intraop_complications are
    # complication slugs — route through ``_localize_complication``
    # so JA reads 「術前診断：大腿骨近位部骨折」 rather than
    # 「術前診断：hip_fracture」.
    preop_disp = _localize_complication(preop, lang) if preop else ""
    postop_disp = _localize_complication(postop, lang) if postop else ""
    intraop_disp = [_localize_complication(str(c), lang) for c in intraop]
    parts = []
    if body_site:
        parts.append(t("op_note.findings_line", lang, body_site=body_site))
    if preop_disp:
        parts.append(t("op_note.findings_preop", lang, dx=preop_disp))
    if postop_disp and postop_disp != preop_disp:
        parts.append(t("op_note.findings_postop", lang, dx=postop_disp))
    if intraop_disp:
        sep = t("list_sep.serial", lang)
        parts.append(t("op_note.findings_intraop", lang, list=sep.join(intraop_disp)))
    else:
        parts.append(t("op_note.findings_intraop_none", lang))
    chunk_sep = t("list_sep.slash", lang)
    return chunk_sep.join(parts) if parts else t("op_note.findings_none_default", lang), facts


def build_op_course(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """手術経過 — approach + duration + outcome + timing narrative."""
    lang = ctx.target_lang
    proc = generator._primary_surgical_procedure(ctx)
    if proc is None:
        return t("op_note.course_not_documented", lang), []
    facts = ["ctx.procedures"]
    approach_raw = str(_o(proc, "approach", "") or "").lower()
    approach = _localize_op_approach(approach_raw, lang)
    duration = _o(proc, "duration_minutes", 0) or 0
    outcome_code = str(_o(proc, "outcome_code", "") or "")
    # ``_OP_OUTCOME_JA/EN`` moved to
    # ``narrative_labels.yaml::op_outcome_code`` (Phase 1d-24).
    outcome = _label("op_outcome_code", outcome_code, lang, fallback="") if outcome_code else ""
    start_dt = _o(proc, "start_datetime", None)
    end_dt = _o(proc, "end_datetime", None)
    approach_part = ""
    if approach:
        # Phase 1d-78: widen from endswith to substring — the raw
        # yaml fallback strings (e.g. "laparoscopic approach with
        # 4-port technique") carry "approach" in the MIDDLE, not
        # at the end. Endswith-only detection let the template
        # append a second " approach" → "…technique approach"
        # (US) or "…technique アプローチにて" (JA on unmapped
        # composite). Substring detection catches both cases.
        approach_lower = approach.lower()
        already_has_suffix = "approach" in approach_lower or "アプローチ" in approach
        key = "op_note.course_approach_part_bare" if already_has_suffix else "op_note.course_approach_part"
        approach_part = t(key, lang, approach=approach)
    time_part = ""
    if isinstance(start_dt, datetime) and isinstance(end_dt, datetime):
        time_part = t(
            "op_note.course_time_part",
            lang,
            start=start_dt.strftime("%H:%M"),
            end=end_dt.strftime("%H:%M"),
        )
    duration_part = t("op_note.course_duration_part", lang, duration=duration) if duration else ""
    outcome_part = t("op_note.course_outcome_part", lang, outcome=outcome) if outcome else ""
    return (
        t(
            "op_note.course_head",
            lang,
            approach_part=approach_part,
            time_part=time_part,
            duration_part=duration_part,
            outcome_part=outcome_part,
        ),
        facts,
    )


def build_op_specimens(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """摘出臓器・組織 — specimens_sent list."""
    lang = ctx.target_lang
    proc = generator._primary_surgical_procedure(ctx)
    if proc is None:
        return t("op_note.specimens_not_documented", lang), []
    facts = ["ctx.procedures"]
    specimens = [str(s) for s in (_o(proc, "specimens_sent", []) or []) if s]
    if not specimens:
        return t("op_note.specimens_none", lang), facts
    sep = t("list_sep.serial", lang)
    return t("op_note.specimens_line", lang, list=sep.join(specimens)), facts


def build_op_blood_loss(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """出血量・輸血 — estimated_blood_loss_ml + transfusion note."""
    lang = ctx.target_lang
    proc = generator._primary_surgical_procedure(ctx)
    if proc is None:
        return t("op_note.blood_loss_not_documented", lang), []
    facts = ["ctx.procedures"]
    ebl = _o(proc, "estimated_blood_loss_ml", 0) or 0
    # Transfusion inference: check ctx.procedures for a blood_transfusion
    # ProcedureRecord in the same encounter (K920 / procedure_type
    # "blood_transfusion" from clinosim.modules.procedure.engine).
    enc_id = _o(ctx.encounter, "encounter_id", "") or ""
    transfused = any(
        (_o(p, "encounter_id", "") == enc_id and str(_o(p, "procedure_type", "") or "").lower() == "blood_transfusion")
        for p in (ctx.procedures or [])
    )
    transfusion_part = t(
        "op_note.blood_loss_transfusion_yes" if transfused else "op_note.blood_loss_transfusion_no",
        lang,
    )
    return t("op_note.blood_loss_line", lang, ebl=ebl, transfusion_part=transfusion_part), facts


def build_op_equipment(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """使用機器・材料 — implants_used list."""
    lang = ctx.target_lang
    proc = generator._primary_surgical_procedure(ctx)
    if proc is None:
        return t("op_note.equipment_not_documented", lang), []
    facts = ["ctx.procedures"]
    implants = [str(x) for x in (_o(proc, "implants_used", []) or []) if x]
    if not implants:
        return (t("op_note.implants_none", lang)), facts
    # Route each implant name through the
    # `narrative_op_implants.yaml` translation table. Case-
    # insensitive lookup on the full string; unmapped names pass
    # through unchanged. Only JA has a translation table today,
    # so `_localize_op_implant(x, "en")` returns `x` verbatim
    # — dropping the outer `lang == "ja"` guard is a no-op and
    # keeps the callsite lang-agnostic.
    implants = [_localize_op_implant(x, lang) for x in implants]
    sep = t("list_sep.serial", lang)
    return t("op_note.equipment_head", lang, list=sep.join(implants)), facts


def build_op_postop_plan(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """術後方針 — recovery destination + monitoring plan (derived)."""
    lang = ctx.target_lang
    proc = generator._primary_surgical_procedure(ctx)
    if proc is None:
        return t("op_note.postop_plan_not_documented", lang), []
    facts = ["ctx.procedures"]
    enc_type_raw = _o(ctx.encounter, "encounter_type", None)
    enc_type = str(_o(enc_type_raw, "value", enc_type_raw) or "").lower()
    outcome_code = str(_o(proc, "outcome_code", "") or "")
    intraop = list(_o(proc, "intraop_complications", []) or [])
    # Recovery destination: ICU/high-acuity or general ward
    icu_flag = enc_type == "icu" or bool(intraop) or outcome_code == "385670004"
    dest = t("op_note.postop_dest_icu" if icu_flag else "op_note.postop_dest_ward", lang)
    monitor = t("op_note.postop_monitor", lang)
    return t("op_note.postop_plan_line", lang, dest=dest, monitor=monitor), facts


# ─────────────────────────────────────────────────────────────────────
# PROCEDURE_NOTE (LOINC 28570-0) — bedside / minor-procedure note.
#
# Each builder resolves the ProcedureRecord identified by
# ``ctx.related_procedure_id`` (populated per-stub by
# ``NarrativePass.run``) out of ``ctx.procedures`` and renders one
# section of the note. When the procedure is missing (defensive
# fallback — should never happen because the enricher only creates a
# stub when a matching ProcedureRecord exists) the builders emit a
# short "記録なし" / "not documented" line rather than raising, so a
# single stale narrative version never blocks the whole pipeline.
# ─────────────────────────────────────────────────────────────────────


def _pn_resolve_procedure(ctx: NarrativeContext) -> tuple[Any | None, list[str]]:
    """Locate the ProcedureRecord this stub describes."""
    proc_id = str(getattr(ctx, "related_procedure_id", "") or "")
    if not proc_id:
        return None, []
    for proc in ctx.procedures or []:
        if str(_o(proc, "procedure_id", "") or "") == proc_id:
            return proc, [f"ctx.procedures[{proc_id}]"]
    return None, []


def build_pn_procedure_name(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """処置名 / Procedure name — resolved from procedure_code."""
    lang = ctx.target_lang
    proc, facts = _pn_resolve_procedure(ctx)
    if proc is None:
        return t("proc_note.procedure_not_documented", lang), facts
    code_jp = str(_o(proc, "procedure_code_jp", "") or "")
    code_us = str(_o(proc, "procedure_code_us", "") or "")
    code = str(_o(proc, "procedure_code", "") or "")
    # Pick the locale-appropriate code system for the display lookup.
    # JA-locale prefers ``code_jp`` (K-codes / 診療報酬点数コード),
    # other locales prefer ``code_us`` (CPT); fall back to the base
    # ``code`` field when the locale-specific slot is empty.
    if lang == "ja" and code_jp:
        primary_code = code_jp
        system_key = "k-codes"
    elif lang != "ja" and code_us:
        primary_code = code_us
        system_key = "cpt"
    else:
        primary_code = code
        system_key = "k-codes"
    display = code_lookup(system_key, primary_code, lang) or primary_code or ""
    proc_type = str(_o(proc, "procedure_type", "") or "")
    # Phase 1c-6 (2026-09-23): localize the procedure_type slug
    # (urinary_catheter / central_line / intubation / …) via the
    # bedside-procedures SoT so JA emits 「術式区分: 尿道カテーテル
    # 挿入」 rather than 「術式区分: urinary_catheter」.
    proc_type_display = _localize_proc_type(proc_type, lang) if proc_type else ""
    facts.append("ctx.procedures.procedure_code")
    core = t("proc_note.procedure_head", lang, display=display)
    if primary_code:
        core += t("proc_note.procedure_code_paren", lang, code=primary_code)
    if proc_type_display:
        core += t("proc_note.procedure_type_suffix", lang, ptype=proc_type_display)
    return core + t("list_sep.period", lang), facts


def build_pn_consent(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """インフォームド・コンセント / Consent — boilerplate.

    clinosim does not model per-Procedure consent artefacts. The
    template emits the standard "consent obtained" phrase every real
    JP electronic-chart procedure note carries; sites that need a
    richer consent trail should record it upstream (Order /
    Procedure.note) and extend this builder.
    """
    _proc, facts = _pn_resolve_procedure(ctx)
    lang = ctx.target_lang
    return t("proc_note.consent_line", lang), facts


def build_pn_performer(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """実施者 / Performer — from ProcedureRecord.primary_surgeon_id."""
    lang = ctx.target_lang
    proc, facts = _pn_resolve_procedure(ctx)
    if proc is None:
        return t("proc_note.operator_not_documented", lang), facts
    performer_id = str(_o(proc, "primary_surgeon_id", "") or "")
    assistant_ids = list(_o(proc, "assistant_ids", []) or [])
    anesth_id = str(_o(proc, "anesthesiologist_id", "") or "")

    # Roster lookup — if the pass populated ``ctx.roster_map`` we can
    # substitute the raw id with a full name; otherwise the raw id
    # goes through and downstream roster localizers may still
    # rewrite it (feedback: staff-id leak was already fixed for
    # Composition, this keeps parity).
    def _localise(raw_id: str) -> str:
        entry = (ctx.roster_map or {}).get(raw_id) if raw_id else None
        if entry:
            name = str(_o(entry, "name", "") or _o(entry, "display", "") or raw_id)
            return t("proc_note.performer_role_suffix", lang, name=name)
        return raw_id

    performer = _localise(performer_id)
    assistants = [_localise(a) for a in assistant_ids if a]
    anesth = _localise(anesth_id) if anesth_id else ""
    facts.extend(["ctx.procedures.primary_surgeon_id"])
    parts = [
        t("proc_note.performer_head", lang, performer=performer) if performer else t("proc_note.performer_none", lang)
    ]
    if assistants:
        # Assistants join uses ", " for both locales in the source
        # (JA also used ", " inline). Preserve that.
        parts.append(t("proc_note.performer_assistants", lang, list=", ".join(assistants)))
    if anesth:
        parts.append(t("proc_note.performer_anesth", lang, name=anesth))
    return t("list_sep.period_space", lang).join(parts) + t("list_sep.period", lang), facts


def build_pn_analgesia(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """麻酔・鎮静 / Analgesia — from ProcedureRecord.anesthesia_type."""
    lang = ctx.target_lang
    proc, facts = _pn_resolve_procedure(ctx)
    if proc is None:
        return t("proc_note.analgesia_not_documented", lang), facts
    anesth = str(_o(proc, "anesthesia_type", "") or "").strip().lower()
    # Bedside procedures use local / sedation almost exclusively —
    # if the record says "general" we still honor it (some
    # cardioversion cases are done under brief GA). Analgesia
    # vocabulary moved to ``narrative_labels.yaml::pn_analgesia_type``
    # (Phase 1d-25). Fallback is ``local`` (bedside procedures default).
    default_method = _label("pn_analgesia_type", "local", lang)
    method = _label("pn_analgesia_type", anesth, lang, fallback=default_method)
    facts.append("ctx.procedures.anesthesia_type")
    return t("proc_note.analgesia_line", lang, method=method), facts


def build_pn_course(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """処置経過 / Procedure course — from duration + approach + outcome."""
    lang = ctx.target_lang
    proc, facts = _pn_resolve_procedure(ctx)
    if proc is None:
        return t("proc_note.course_not_documented", lang), facts
    duration = int(_o(proc, "duration_minutes", 0) or 0)
    approach = str(_o(proc, "approach", "") or "")
    outcome_code = str(_o(proc, "outcome_code", "") or "")
    # SNOMED outcome codes 385669000 / 385670004 / 385671000 moved
    # to ``narrative_labels.yaml::pn_outcome_code`` (Phase 1d-25).
    # Missing / unknown code falls back to the "planned completion"
    # phrase (still language-agnostic via the same YAML).
    outcome_default = t("proc_note.course_outcome_default", lang)
    outcome = (
        _label("pn_outcome_code", outcome_code, lang, fallback=outcome_default) if outcome_code else outcome_default
    )
    facts.extend(["ctx.procedures.duration_minutes", "ctx.procedures.outcome_code"])
    core = t("proc_note.course_duration_head", lang, duration=duration)
    if approach:
        core += t("proc_note.course_approach_part", lang, approach=approach)
    return core + t("proc_note.course_outcome_suffix", lang, outcome=outcome), facts


def build_pn_complications(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """合併症の有無 / Complications — from intraop_complications + complication_codes."""
    lang = ctx.target_lang
    proc, facts = _pn_resolve_procedure(ctx)
    if proc is None:
        return t("proc_note.complications_not_documented", lang), facts
    intraop = [str(x) for x in (_o(proc, "intraop_complications", []) or []) if x]
    codes = [str(x) for x in (_o(proc, "complication_codes", []) or []) if x]
    facts.append("ctx.procedures.intraop_complications")
    if intraop or codes:
        code_display = []
        for c in codes:
            disp = code_lookup("snomed-ct", c, lang) or c
            code_display.append(t("list_item.inline_dx_with_code", lang, display=disp, code=c))
        all_items = intraop + code_display
        # Complications use "; " in EN (semicolon-space) not "; ".
        # Reuse list_sep.semicolon which is 「、」 / 「; 」.
        sep = t("list_sep.semicolon", lang)
        joined = sep.join(all_items)
        return t("proc_note.complications_present", lang, list=joined), facts
    return t("proc_note.complications_none", lang), facts


def build_pn_specimens(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """検体の有無 / Specimens — from ProcedureRecord.specimens_sent."""
    lang = ctx.target_lang
    proc, facts = _pn_resolve_procedure(ctx)
    if proc is None:
        return t("proc_note.specimens_not_documented", lang), facts
    specimens = [str(x) for x in (_o(proc, "specimens_sent", []) or []) if x]
    facts.append("ctx.procedures.specimens_sent")
    if specimens:
        sep = t("list_sep.serial", lang)
        joined = sep.join(specimens)
        return t("proc_note.specimens_present", lang, list=joined), facts
    return t("proc_note.specimens_none", lang), facts


def build_pn_postop_plan(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """術後方針 / Post-procedure plan — outcome-aware boilerplate."""
    lang = ctx.target_lang
    proc, facts = _pn_resolve_procedure(ctx)
    if proc is None:
        return t("proc_note.postop_plan_not_documented", lang), facts
    outcome_code = str(_o(proc, "outcome_code", "") or "")
    facts.append("ctx.procedures.outcome_code")
    # Simple, defensible plans: baseline monitoring for successful
    # procedures; escalation-of-care phrasing for unsuccessful ones.
    if outcome_code == "385671000":
        return t("proc_note.postop_unsuccessful", lang), facts
    return t("proc_note.postop_baseline", lang), facts
