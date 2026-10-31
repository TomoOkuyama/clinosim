"""``_build_extra_context`` and its small ``_writing_day_of`` sibling —
the entry point that composes every per-section renderer into a single
LLM-prompt context dict.

Fourth mechanical slice of the META #1633 P6 ``replacement_strategy``
decomposition. The two helpers lift cleanly as a pair because
``_build_extra_context`` is the sole caller of ``_writing_day_of`` and
``_writing_day_of`` reads ``_WRITING_DAY_SCOPE`` which already lives in
``_patient_info_renderers.py``.

Zero behaviour change: ``replacement_strategy.py`` re-exports both
names via explicit ``from … import X as X`` aliases.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from clinosim.codes import display as registry_display
from clinosim.locale.i18n import t
from clinosim.modules._shared import pick_localized_field
from clinosim.modules.document.narrative._patient_info_renderers import (
    _WRITING_DAY_SCOPE,
    _health_literacy_tag,
    _render_patient_biometrics,
    _render_patient_demographics,
)
from clinosim.modules.document.narrative._replacement_localization import (
    _localize_arrival_mode_ja,
    _localize_severity_ja,
    _lookup_ja_label,
)
from clinosim.modules.document.narrative._replacement_renderers import (
    _get,
    _render_abnormal_labs,
    _render_active_meds,
    _render_chronic_list,
    _render_first_vitals,
    _render_key_procedures,
    _render_lab_carry_forward,
    _render_lab_trend_today,
    _render_med_names,
    _render_newborn_workup_summary,
    _render_supplemental_oxygen_today,
    _render_vitals_for_day,
    _render_vitals_range,
    _stay_phase,
)
from clinosim.types.document import DocumentTypeSpec, NarrativeContext

# Per-doc-type extras eligibility — biometrics (Ht/Wt/BMI/blood type) and
# health_literacy_tag — is defined in
# `clinosim/modules/document/reference_data/narrative_extras_whitelists.yaml`.
# `_biometrics_doc_types()` / `_health_literacy_doc_types()` load the two
# allow-lists lazily and `@cache`-memoize them; call them at the use site
# instead of the former module-level constants.


@cache
def _narrative_extras_whitelists() -> dict[str, frozenset[str]]:
    import yaml

    path = Path(__file__).resolve().parents[1] / "reference_data" / "narrative_extras_whitelists.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    out: dict[str, frozenset[str]] = {}
    for key in ("biometrics", "health_literacy"):
        rows = raw.get(key) or []
        out[key] = frozenset(str(r) for r in rows if isinstance(r, str))
    return out


def _biometrics_doc_types() -> frozenset[str]:
    return _narrative_extras_whitelists()["biometrics"]


def _health_literacy_doc_types() -> frozenset[str]:
    return _narrative_extras_whitelists()["health_literacy"]


def _writing_day_of(spec: DocumentTypeSpec, ctx: NarrativeContext) -> int | None:
    """Return the 0-indexed hospital day at which this document is written,
    or ``None`` for whole-stay scope (no temporal filter).

    Compared against ``working_diagnoses[i].onset_day`` (also 0-indexed
    calendar days since admission — see ``simulator/engine.py::
    _merge_disease_into_active_encounter`` where onset_day is computed as
    ``(event_time.date() - admit_dt.date()).days``). A complication whose
    ``onset_day > writing_day`` has not yet occurred by the writer's clock
    and must be filtered out (see the ``complications_during_stay`` /
    ``in_hospital_new_diagnoses`` block below).

    Whole-stay scope (``None``) preserves the pre-filter behaviour for
    discharge_summary / death_* / referral_note — those documents are
    authored at or near discharge and legitimately know the full timeline.
    """
    scope = _WRITING_DAY_SCOPE.get(getattr(spec, "type_key", ""), "whole_stay")
    if scope == "day_of_stub":
        return int(getattr(ctx, "day_index", 0) or 0)
    if scope == "admission":
        return 0
    return None


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
    home_medications ↔ medications_at_home, todays_vitals_summary ↔
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
            rendered = _render_chronic_list(chronic, lang=ctx.target_lang)
            if rendered:
                extra["chronic_conditions"] = rendered

    # ---- Session 104 Tier 1 realism keys ----------------------------
    # Three new keys surface patient-profile facts previously hidden
    # from the LLM (SOAP-shaped docs — progress_note / outpatient_soap /
    # ed_note — see NO template social_history / biometrics sections,
    # so the LLM had only `patient_bucket` decade-granularity for
    # demographics). Additive; docs that already carry the equivalent
    # template section (admission_hp social_history / medications_at_home)
    # skip via the same `tmpl` gate the chronic_conditions block uses.
    if p is not None:
        _demo = _render_patient_demographics(p, lang=ctx.target_lang, encounter=getattr(ctx, "encounter", None))
        if _demo and "social_history" not in tmpl:
            extra["patient_demographics"] = _demo
        # Biometrics: emit for doc types where BMI / blood type carry
        # narrative weight (surgical / anaesthesia / procedure / discharge
        # planning). Also emit whenever the template does NOT already
        # render `physical_examination` (which typically states vitals
        # but not height / weight / blood type).
        if doc_type in _biometrics_doc_types():
            _bio = _render_patient_biometrics(p, lang=ctx.target_lang)
            if _bio:
                extra["patient_biometrics"] = _bio
        # Health-literacy tag: 3-band discretisation drives the tone of
        # patient-facing narrative (discharge_instructions, referral
        # letter courtesy, family_communication register). LOCALE-INVARIANT
        # tag — the prompt localises the tone rules per language.
        if doc_type in _health_literacy_doc_types():
            _hl = _health_literacy_tag(p)
            if _hl:
                extra["health_literacy_tag"] = _hl

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
        # session-88j Phase B: severity token (mild/moderate/severe)
        # leaks into JA narratives verbatim (v14 review: 634 mild + 442
        # moderate mentions across 1,386 doc). Localize for JA prompts.
        sev_label = _localize_severity_ja(str(ctx.severity)) if ctx.target_lang == "ja" else ctx.severity
        scenario_bits.append(f"severity={sev_label}")
    if scenario_bits:
        extra["clinical_scenario"] = " / ".join(scenario_bits)
    if ctx.los_days and ctx.los_days > 0:
        phase = _stay_phase(ctx.day_index, ctx.los_days, ctx.target_lang)
        # Phase 1d-79: locale-aware stay_progress. Pre-1d-79 the value was
        # hard-coded English ("day N of expected M (middle / stabilisation
        # phase)"); the LLM copied it verbatim into JA prose, producing
        # visible EN leaks (「入院5日目（middle / stabilisation phase）」).
        if ctx.target_lang == "ja":
            hd = ctx.day_index + 1  # 1-indexed hospital day
            extra["stay_progress"] = f"入院{hd}日目 / 予定{ctx.los_days}日 ({phase})"
        else:
            extra["stay_progress"] = f"day {ctx.day_index} of expected {ctx.los_days} ({phase})"

    # v7 fix (2026-08-17): explicit 1-indexed hospital day label. v6
    # passed only day_index (0-indexed) and the LLM systematically
    # misread day_index=1 as "入院初日" (v9 review: 11/11 doc-03 all
    # wrote "入院初日で" on day 1). Injecting the ready-to-use JA/EN
    # phrase eliminates the interpretation gap.
    if ctx.los_days and ctx.los_days > 0:
        hd = ctx.day_index + 1  # 1-indexed
        if ctx.target_lang == "ja":
            extra["hospital_day_label"] = "入院初日" if ctx.day_index == 0 else f"入院{hd}日目"
        else:
            extra["hospital_day_label"] = "hospital day 1 (admission)" if ctx.day_index == 0 else f"hospital day {hd}"

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
                extra["encounter_type"] = _lookup_ja_label(et_raw, "encounter_type")[:40]
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
    # ---- Issue #1066 (drug_safety): considered-but-not-prescribed ---
    # Surface the CPOE-style avoidance / substitution log so the LLM can
    # weave the clinical reasoning ("~ was avoided due to concurrent ~; ~
    # was prescribed instead") into the narrative's Assessment & Plan
    # section. This is the Layer-3 (production LLM prompt) leg of the
    # 4-layer narrative integration; Layer 2 (deterministic template) is
    # in template_generator._render_safety_skips_line.
    safety_skips = list(getattr(ctx, "safety_skips", []) or [])
    if safety_skips:
        lang = ctx.target_lang
        lines: list[str] = []
        for s in safety_skips[:8]:  # cap payload (~200 tokens max)
            # Issue #1403: event_type-aware cadence — the narrative
            # prompt Rule 2 (v17) reads a leading marker per bullet
            # to dispatch to the matching clinical phrasing (avoid /
            # hold / substitute / deescalate). Legacy pair-avoid logs
            # (event_type absent) fall through to "avoid".
            # Issue #1413 (S114): switch/deescalate keep neutral
            # "X discontinued → Y started" prose — no direction
            # assertion (real treatment_modifications stops are mostly
            # escalations, so a spectrum-agnostic phrasing is safer).
            event = str(s.get("event_type") or "avoid").lower()
            # `<field>_<lang>` slot with bare-slot fallback via the
            # shared CIF-slot picker — no `lang == "ja"` gate here so
            # adding a locale is a data-only change (populate
            # `<field>_<lang>` on the safety-skip entry).
            considered = pick_localized_field(s, "considered", lang)
            conflict = pick_localized_field(s, "avoided_due_to", lang)
            substituted = pick_localized_field(s, "substituted_with", lang) or None
            day = s.get("stopped_on_day")
            day_phrase = (
                t("safety_skips.day_phrase_specific", lang, day=int(day))
                if day
                else t("safety_skips.day_phrase_default", lang)
            )
            if event == "hold":
                key = "safety_skips_prompt.hold"
            elif event == "substitute":
                key = (
                    "safety_skips_prompt.substitute_with_sub"
                    if substituted
                    else "safety_skips_prompt.substitute_no_sub"
                )
            elif event == "switch":
                key = "safety_skips_prompt.switch_with_sub" if substituted else "safety_skips_prompt.switch_no_sub"
            elif event == "deescalate":
                key = (
                    "safety_skips_prompt.deescalate_with_sub"
                    if substituted
                    else "safety_skips_prompt.deescalate_no_sub"
                )
            else:  # avoid (legacy + explicit)
                key = "safety_skips_prompt.avoid_with_sub" if substituted else "safety_skips_prompt.avoid_no_sub"
            lines.append(
                t(
                    key,
                    lang,
                    considered=considered,
                    conflict=conflict,
                    substituted=substituted or "",
                    day_phrase=day_phrase,
                )
            )
        extra["considered_but_not_prescribed"] = "\n".join(lines)

    complications = list(getattr(ctx, "complications_occurred", []) or [])
    if complications:
        # Issue #848: when the complication is an in-hospital new-disease
        # event (from engine._merge_disease_into_active_encounter), the
        # matching ``working_diagnoses`` entry carries an ``onset_day``.
        # Surface that timing to the LLM prompt so the generated
        # narrative can say "入院第30日目に急性心筋梗塞を発症" instead of
        # listing the disease as if it had been an admission-day finding.
        #
        # Temporal-leak filter (Phase 0 2026-09-22 → Phase 1b 2026-09-22):
        # the pre-filter code unconditionally surfaced every complication
        # + every dated new-dx to every LLM call, including day-N
        # progress_notes. Prompt Rule 2 requires the LLM to surface every
        # listed complication → a day-1 progress note for an encounter
        # whose N17.9 AKI onsets on day 13 would narrate "入院初日に急性
        # 腎障害が発症" — physically impossible from the writer's day-1
        # vantage. v0.6.3 JP p=10000 llm-polished audit measured:
        #   - working_diagnoses onset_day >= 2 encounters:  10.1% of
        #     pre-onset docs mention the future dx (190/1874) → closed
        #     by PR #1452 (Phase 0).
        #   - complications_occurred string-name entries (no onset):
        #     49.2% of day-1 notes mention the complication (905/1841)
        #     → Phase 1b closes for daily_loop-source entries because
        #     they now carry onset_day directly (Phase 1a schema); the
        #     conservative undated-entry drop stays for the tiny legacy
        #     tail (source="legacy") that still lacks onset_day.
        # Rule 2 stays unchanged — the LLM still surfaces every complication
        # it sees; correctness now lives in what the CONTEXT contains.
        events = list(getattr(ctx, "complications_events", []) or [])
        _wds = list(getattr(ctx, "working_diagnoses", []) or [])
        _onset_by_disease = {
            str(wd.get("disease_id", "")): wd.get("onset_day")
            for wd in _wds
            if isinstance(wd, dict) and wd.get("onset_day") is not None
        }
        # Merge onset info from complications_events (Phase 1a schema —
        # every dict entry carries its own onset_day when known). For a
        # complication that appears in both the daily-loop and the
        # working_diagnoses paths (some paths cross-write) the events
        # onset wins because it is source-of-truth for the dispatching
        # producer.
        _onset_from_events: dict[str, int | None] = {}
        for evt in events:
            if not isinstance(evt, dict):
                continue
            n = str(evt.get("name") or "")
            if not n:
                continue
            od = evt.get("onset_day")
            if od is None:
                _onset_from_events.setdefault(n, None)
            else:
                _onset_from_events[n] = int(od)

        def _onset_of(name: str) -> int | None:
            """Return the earliest known onset_day for ``name`` (Phase 1b:
            events schema is primary, working_diagnoses is the fallback)."""
            if name in _onset_from_events and _onset_from_events[name] is not None:
                return _onset_from_events[name]
            wd_onset = _onset_by_disease.get(name)
            if wd_onset is not None:
                return int(wd_onset)
            return None

        writing_day = _writing_day_of(spec, ctx)
        # Phase 1d-77: pre-localize the complication tokens so the JA LLM
        # context sees 「気胸」「低カリウム血症」「尿路性敗血症」etc.
        # rather than raw slugs (pneumothorax / hypokalemia / urosepsis).
        # Matches the template-path fix (Phase 1d-72) that routes death_cert
        # + dds complications through _localize_complication. Rule 3 verbatim
        # then applies cleanly — the LLM copies the already-localized display
        # instead of relying on parametric-memory translation.
        #
        # ICD codes (e.g. "N17.9") mix into complications_occurred alongside
        # English slugs; they must render via code_lookup (JP → icd-10-mhlw)
        # not _localize_complication (which lowercases keys and misses).
        # Presence of a digit-and-dot signals the ICD form.
        import re as _re

        from clinosim.modules.document.narrative.template_generator import (
            _localize_complication,
        )

        _icd_pat = _re.compile(r"^[A-Z]\d")

        def _disp(cid: str) -> str:
            if _icd_pat.match(cid):
                # ICD code — resolve via code_lookup on the JA/EN diagnosis
                # code system; fall back to the raw code when unmapped.
                sys_key = "icd-10-mhlw" if ctx.locale == "jp" else "icd-10-cm"
                return registry_display(sys_key, cid, ctx.target_lang) or cid
            return _localize_complication(cid, ctx.target_lang) or cid

        # Phase 1d-79: locale-aware onset phrase. Pre-1d-79 the format was
        # hard-coded English (`(hospital-day N onset)`) which the LLM copied
        # verbatim into JA prose ("急性腎障害 (hospital-day 2 onset)").
        def _onset_suffix(onset_day: int) -> str:
            if ctx.target_lang == "ja":
                return f"（入院{onset_day}日目発症）"
            return f"(hospital-day {onset_day} onset)"

        _phrases: list[str] = []
        for c in complications[:10]:
            cid = str(c)
            onset = _onset_of(cid)
            if onset is not None:
                if writing_day is not None and int(onset) > writing_day:
                    continue  # future event, not yet occurred at writing time
                if int(onset) > 0:
                    _phrases.append(f"{_disp(cid)} {_onset_suffix(int(onset))}")
                else:
                    _phrases.append(_disp(cid))
            else:
                # Undated entry (no matching events/working_diagnoses
                # onset). After Phase 1a producers this is only the
                # ``source="legacy"`` tail — pre-Phase-1 CIF JSON we still
                # read for backward compat. Retain for whole-stay scope
                # only; a day-scoped or admission-scoped narrative cannot
                # safely place an untimed event on the writer's clock.
                if writing_day is None:
                    _phrases.append(_disp(cid))
        if _phrases:
            extra["complications_during_stay"] = "; ".join(_phrases)

        # in_hospital_new_diagnoses: the working_diagnoses list carries
        # dated in-hospital new-dx entries. Filter by writing_day so day-N
        # notes never see future new dx.
        # Phase 1d-79: locale-aware format (JA gets 「入院N日目発症」).
        def _new_dx_line(disease: str, onset_day: int) -> str:
            if ctx.target_lang == "ja":
                return f"入院{onset_day}日目に{disease}"
            return f"{disease} on hospital day {onset_day}"

        filtered_new_dx = [
            _new_dx_line(did, int(od))
            for did, od in _onset_by_disease.items()
            if od is not None and (writing_day is None or int(od) <= writing_day)
        ]
        if filtered_new_dx:
            extra["in_hospital_new_diagnoses"] = "; ".join(filtered_new_dx)

    # ---- Doc-type-specific ----
    if doc_type in ("progress_note", "nursing_shift_note"):
        # Day-N context: today's vital snapshot + active meds
        # todays_vitals_summary skipped only when template's objective
        # already renders vitals (empirically progress_note's objective
        # is exam narrative not vitals — so keep the vitals summary).
        today_vitals = _render_vitals_for_day(ctx.vitals, ctx.day_index, enc)
        if today_vitals:
            extra["todays_vitals_summary"] = today_vitals
        active_meds = _render_active_meds(ctx.medications, ctx.day_index, lang=ctx.target_lang)
        if active_meds:
            extra["active_medications_today"] = active_meds
        # Session-90 fix: today's abnormal labs, trend vs prior draw,
        # and carry-forward "current state" of abnormal tests not
        # redrawn today. Previously the day-filter was broken (see
        # `_render_abnormal_labs` docstring) so every day's progress
        # note quoted the admission labs verbatim.
        adm_dt = _get(enc, "admission_datetime")
        abnormal_today = _render_abnormal_labs(
            ctx.lab_results, day_index=ctx.day_index, lang=ctx.target_lang, admission_datetime=adm_dt
        )
        if abnormal_today:
            extra["abnormal_labs_today"] = abnormal_today
        if adm_dt is not None:
            trend_today = _render_lab_trend_today(ctx.lab_results, ctx.day_index, adm_dt, lang=ctx.target_lang)
            if trend_today:
                extra["lab_trend_today"] = trend_today
            carry_forward = _render_lab_carry_forward(ctx.lab_results, ctx.day_index, adm_dt, lang=ctx.target_lang)
            if carry_forward:
                extra["lab_current_state"] = carry_forward
        # v6 blocker fix: supplemental oxygen flag. Prevents "SpO2 89%
        # だが酸素投与なしで安定" self-contradiction (POP-000075 doc-06).
        o2_today = _render_supplemental_oxygen_today(ctx.vitals, ctx.day_index, enc, lang=ctx.target_lang)
        if o2_today:
            extra["supplemental_oxygen_today"] = o2_today
    elif doc_type == "admission_hp":
        # home_medications: skip when template renders medications_at_home.
        if "medications_at_home" not in tmpl:
            home_meds = _get(p, "current_medications", []) or _get(p, "medications", []) or []
            med_names = _render_med_names(home_meds, lang=ctx.target_lang)
            if med_names:
                extra["home_medications"] = med_names
        # Issue #1404: neonatal admission_hp — emit a one-line workup
        # summary the LLM Rule 2 / per-doc-type block reads to weave
        # Apgar / AABR / metabolic-screen / bilirubin / CCHD / Vitamin K
        # into HPI + A&P. Empty for non-neonate records (guarded by the
        # ctx builder's `is_neonate` gate). See `narrative_seed_bundle`
        # neonatal admission_hp block for the expected cadence.
        newborn_workup = getattr(ctx, "newborn_workup", None) or {}
        if newborn_workup.get("is_neonate"):
            summary = _render_newborn_workup_summary(newborn_workup, lang=ctx.target_lang)
            if summary:
                extra["newborn_workup_summary"] = summary
    elif doc_type == "discharge_summary":
        # discharge_medications_list: skip when template renders it.
        if "discharge_medications" not in tmpl:
            dmed = ctx.discharge_medications or []
            dmed_names = _render_med_names(dmed, lang=ctx.target_lang)
            if dmed_names:
                extra["discharge_medications_list"] = dmed_names
        outcome = _get(enc, "discharge_disposition") or _get(enc, "discharge_status")
        if outcome:
            outcome_raw = str(outcome)[:120]
            # v6 localization: `home` → `自宅退院` for JA prompts. LLM
            # was pasting the raw disposition code into JA hospital_course.
            # session-88j Phase B: case-insensitive lookup so CIF enums
            # like transfer_to_higher_care / home_with_family / needs_snf
            # are recognized alongside the legacy short codes.
            if ctx.target_lang == "ja":
                extra["discharge_outcome"] = _lookup_ja_label(outcome_raw, "disposition")
            else:
                extra["discharge_outcome"] = outcome_raw
        # v6 blocker fix: hospital_course was collapsing to a 1-liner
        # template because LLM had nothing specific to work with.
        # Feed the whole-stay lab/procedure/vitals-extremes summary.
        abnormal_stay = _render_abnormal_labs(ctx.lab_results, day_index=None, lang=ctx.target_lang)
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
        # medications section). todays_vitals_summary: skip when
        # template's `objective` already contains today's vitals numeric
        # summary (outpatient_soap.objective renders BP/HR/RR/SpO2/T
        # verbatim from vitals — same info). Naming normalized S113→S114:
        # outpatient_soap previously used the singular `today_vitals_summary`
        # while progress_note used `todays_vitals_summary`; the bundle
        # prompt Context contract only lists the `todays_` form, so the
        # outpatient_soap variant was silently missing from prompt guidance.
        home_meds = _get(p, "current_medications", []) or _get(p, "medications", []) or []
        # session-88j Phase B fix: outpatient_soap home_medications was
        # rendering EN drug names (Amlodipine / Atorvastatin / …) because
        # _render_med_names defaulted to lang="en" here (bug from PR
        # that added JA drug localization elsewhere — 78+75+44+41 EN
        # drug mentions in v14 review traced to this single line).
        med_names = _render_med_names(home_meds, lang=ctx.target_lang)
        if med_names:
            extra["home_medications"] = med_names
        if "objective" not in tmpl:
            today_vitals = _render_vitals_for_day(ctx.vitals, ctx.day_index, enc)
            if today_vitals:
                extra["todays_vitals_summary"] = today_vitals
        # v6: same lab flag injection as progress_note — outpatient
        # assessment was ignoring AST H, PT_INR H, Cr H etc.
        abnormal_today = _render_abnormal_labs(ctx.lab_results, day_index=None, lang=ctx.target_lang)
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
            # session-88j Phase B: raw arrival_mode enum (walk_in /
            # ambulance) leaks into JA ed_note otherwise. Localize.
            if ctx.target_lang == "ja":
                extra["arrival_mode"] = _localize_arrival_mode_ja(str(arrival))
            else:
                extra["arrival_mode"] = str(arrival)
        # initial_vitals: physical_exam template is narrative not
        # numeric, so numeric arrival vitals are complementary — keep.
        first_vitals = _render_first_vitals(ctx.vitals)
        if first_vitals:
            extra["initial_vitals"] = first_vitals

    return extra
