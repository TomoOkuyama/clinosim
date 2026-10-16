"""Patient-info narrative renderers for the replacement-strategy pipeline.

Third mechanical slice of the META #1633 P6 ``replacement_strategy``
decomposition (first ``_replacement_localization.py`` #1674, second
``_replacement_renderers.py`` #1675). Four cohesive helpers that
render patient demographics / biometrics / health-literacy anchor
lines + the shared ``_localize_token`` enum-to-locale lookup move
from ``replacement_strategy.py`` to this sibling.

Zero behaviour change: ``replacement_strategy.py`` re-exports every
moved name via explicit ``from … import X as X`` aliases so (a)
external callers (tests importing the helpers) keep their import
path, and (b) mypy treats them as deliberately re-exported.
"""

from __future__ import annotations

from typing import Any

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative._replacement_renderers import _get


def _localize_token(token: str, section: str, lang: str) -> str:
    """Look a raw enum-like token up in the named LLM-prompt-labels
    section. Returns "" for empty / unknown / None input; falls back
    to a lower-case slug for tokens the table does not know.

    Language-agnostic: ``lang`` is used as a direct key into the YAML
    entry (via ``resolve_localized_display``), so adding a new locale
    is a data-only change — no branch in this function needs editing.
    """
    if not token:
        return ""
    key = str(token).strip().lower()
    if not key or key in ("unknown", "none"):
        return ""
    from clinosim.locale.loader import load_llm_prompt_labels, resolve_localized_display

    return resolve_localized_display(
        load_llm_prompt_labels().get(section, {}).get(key, {}),
        lang,
        fallback=key.replace("_", " "),
    )


def _render_patient_demographics(patient: Any, lang: str, encounter: Any = None) -> str:
    """Compose a one-line demographic anchor (age / sex / occupation /
    social history / marital / insurance). Used as the LLM's primary
    background reference for SOAP-shaped docs whose template layer does
    NOT render a social_history section. Missing fields drop silently
    (never fabricate).

    Issue #1173 follow-up (S104 verify): the previous version read
    `patient.age` — the static sim-start age — which under-reported by
    1-2 y whenever the encounter fell later in the sim window. When
    ``encounter`` is passed and both ``patient.date_of_birth`` and
    ``encounter.admission_datetime`` are available, derive the true
    age at the encounter date. Falls back to static ``patient.age``
    when either field is missing (safe default).
    """
    age = _get(patient, "age", None)
    # Age-at-encounter override — Issue #1173 verify gap.
    # #1173 verify 2nd pass: CIF `date_of_birth` may be a `date` or an
    # ISO string ("1990-06-25"). `.year` on a string raised silently-
    # swallowed AttributeError → static age used → 94-96% stale headers.
    # Normalize both shapes below.
    from datetime import date as _date
    from datetime import datetime as _datetime

    dob_raw = _get(patient, "date_of_birth", None)
    dob: Any
    if isinstance(dob_raw, str):
        try:
            dob = _date.fromisoformat(dob_raw[:10])
        except ValueError:
            dob = None
    elif dob_raw is not None and hasattr(dob_raw, "year"):
        dob = dob_raw
    else:
        dob = None
    if encounter is not None and dob is not None:
        _adm = _get(encounter, "admission_datetime", None)
        if _adm is not None:
            try:
                if isinstance(_adm, str):
                    ref_date = _date.fromisoformat(_adm[:10])
                elif isinstance(_adm, _datetime):
                    ref_date = _adm.date()
                else:
                    ref_date = _adm
                _computed = (
                    ref_date.year - dob.year - (1 if (ref_date.month, ref_date.day) < (dob.month, dob.day) else 0)
                )
                if _computed >= 0:
                    age = _computed
            except (AttributeError, TypeError, ValueError):
                pass
    sex = _get(patient, "sex", "")

    parts: list[str] = []

    # Age + sex — the leading anchor. Prefer explicit int age; skip
    # entirely if age is missing / None / 0 (unknown).
    if age and isinstance(age, int) and age > 0:
        sex_label = ""
        if sex:
            s = str(sex).strip().lower()
            # Phase 1d-16: sex-label vocabulary moved to
            # ``narrative_labels.yaml::sex_label``. In practice patient
            # sex is populated from a bounded enum ("M" / "F") so the
            # lookup miss path is dead — kept only for defensive parity
            # with the prior ternary's ``.get(s, "")`` semantic.
            from clinosim.locale.loader import (
                load_narrative_labels,
                resolve_localized_display,
            )

            sex_entry = load_narrative_labels().get("sex_label", {}).get(s)
            sex_label = resolve_localized_display(sex_entry, lang, fallback="")
        if sex_label:
            parts.append(t("patient_demographics.age_with_sex", lang, age=age, sex_label=sex_label))
        else:
            parts.append(t("patient_demographics.age_only", lang, age=age))

    # Employment (retired / employed / …) — retired matters for
    # discharge-planning + adherence context.
    #
    # Phase 1c-1 (2026-09-22): the occupation branches previously
    # appended ``str(occupation)`` raw, so JP narratives received the
    # English enum token verbatim ("service"、"manufacturing"、"office"
    # …). Route both branches through ``_localize_token`` /
    # ``"occupation"`` — unknown tokens still fall back to the
    # slug so novel occupations (not yet in the table) surface something
    # rather than silently disappearing.
    employment = _localize_token(_get(patient, "employment_status", ""), "employment", lang)
    occupation_raw = _get(patient, "occupation", "") or ""
    occupation_label = _localize_token(occupation_raw, "occupation", lang) if occupation_raw else ""
    if employment:
        # If occupation is present AND employment==employed, prefer the
        # occupation phrase; else use the employment label. Retirees
        # already carry occupation="retired" which resolves to the same
        # "退職" / "retired" label — dedupe by preferring employment
        # in that case.
        if occupation_label and employment in ("就業中", "employed"):
            parts.append(occupation_label)
        else:
            parts.append(employment)
    elif occupation_label:
        parts.append(occupation_label)

    # Smoking / alcohol — social history.
    smoke = _localize_token(_get(patient, "smoking_status", ""), "smoking", lang)
    if smoke:
        parts.append(smoke)
    alc = _localize_token(_get(patient, "alcohol_use", ""), "alcohol", lang)
    if alc:
        parts.append(alc)

    # Marital status — matters for disposition + family communication.
    marital = _localize_token(_get(patient, "marital_status", ""), "marital", lang)
    if marital:
        parts.append(marital)

    # Insurance — matters for follow-up + referral routing.
    ins = _localize_token(_get(patient, "insurance_type", ""), "insurance", lang)
    if ins:
        parts.append(ins)

    # US Core demographics (Issue #1405 P1 refinement): race + ethnicity
    # are US-only concepts on PatientProfile (US Core Patient must-support
    # extensions #1344 wired them at FHIR emit time). Silently absent for
    # JP records (race / ethnicity strings are empty). Emit them last so
    # they read as the closing demographic anchor rather than intruding
    # on the leading age/sex/social-history clause.
    race = _localize_token(_get(patient, "race", ""), "race", lang)
    if race:
        parts.append(race)
    ethn = _localize_token(_get(patient, "ethnicity", ""), "ethnicity", lang)
    if ethn:
        parts.append(ethn)

    if not parts:
        return ""
    return t("list_sep.serial", lang).join(parts)


def _render_patient_biometrics(patient: Any, lang: str) -> str:
    """Compose Ht / Wt / BMI / blood-type one-liner. Used by surgical
    + anaesthesia + procedure + discharge doc types where these facts
    have narrative weight (dose scaling, transfusion prep, mobility).
    Missing fields drop silently.

    Neonatal / infant framing (S113→S114): when the patient is a
    newborn / infant (``age == 0`` or ``occupation == "infant"``), the
    numeric shape (身長 50 cm / 体重 3.2 kg) reads as adult malnutrition
    to a downstream LLM without an explicit neonatal anchor. Prefix the
    line with 「出生時 / birth」and suppress BMI (乳児 BMI has no
    clinical utility; the CDC/WHO growth curves use weight-for-length
    percentiles instead). Height / weight labels stay the same numeric
    units — only the framing shifts.
    """
    height_cm = _get(patient, "height_cm", None)
    weight_kg = _get(patient, "weight_kg", None)
    bmi = _get(patient, "bmi", None)
    blood_type = _get(patient, "blood_type", "") or ""
    rh = _get(patient, "rh_factor", "") or ""

    _age = _get(patient, "age", None)
    _occupation = str(_get(patient, "occupation", "") or "").strip().lower()
    is_neonate = (isinstance(_age, int) and _age == 0) or _occupation == "infant"

    parts: list[str] = []

    def _pos(v: Any) -> bool:
        try:
            return v is not None and float(v) > 0
        except (TypeError, ValueError):
            return False

    if _pos(height_cm) or _pos(weight_kg):
        h_str = f"{float(height_cm):.0f} cm" if _pos(height_cm) else "-"
        w_str = f"{float(weight_kg):.1f} kg" if _pos(weight_kg) else "-"
        phrase_key = "patient_biometrics.height_weight_neonate" if is_neonate else "patient_biometrics.height_weight"
        parts.append(t(phrase_key, lang, h=h_str, w=w_str))
    # BMI: suppress for neonates / infants (weight-for-length percentile
    # is the pediatric standard; adult BMI cutoffs do not apply < 2 y/o).
    if _pos(bmi) and not is_neonate:
        parts.append(f"BMI {float(bmi):.1f}")
    if blood_type:
        bt = str(blood_type).strip().upper()
        # Format blood type + Rh factor as "O+" / "O-" style. rh_factor
        # comes in as "positive" / "negative" / "+" / "-".
        rh_symbol = ""
        if rh:
            r = str(rh).strip().lower()
            if r in ("positive", "pos", "+"):
                rh_symbol = "+"
            elif r in ("negative", "neg", "-"):
                rh_symbol = "-"
        label = f"{bt}{rh_symbol}" if rh_symbol else bt
        parts.append(t("patient_biometrics.blood_type", lang, label=label))

    if not parts:
        return ""
    return t("list_sep.serial", lang).join(parts)


def _health_literacy_tag(patient: Any) -> str:
    """3-band discretisation of `patient.health_literacy` (0.0-1.0 float):

      < 0.4  → "low"     — LLM should use plain-language phrasing, no
                          Latin medical terms, no abbreviations, short
                          sentences (< 20 words), one instruction per line.
      0.4-0.7 → "medium" — standard patient-facing tone, brief medical
                           terms defined in parenthesis when first used.
      ≥ 0.7  → "high"    — full medical terminology acceptable; the
                           patient can parse standard discharge language.

    Locale-invariant tag; the prompt encodes the per-locale style
    guidance. Returns "" when the field is unset (do NOT default to
    a band — silence is honest)."""
    hl = _get(patient, "health_literacy", None)
    try:
        val = float(hl) if hl is not None else None
    except (TypeError, ValueError):
        return ""
    if val is None:
        return ""
    if val < 0.4:
        return "low"
    if val < 0.7:
        return "medium"
    return "high"


# ---- Temporal-scope map (physician writing-time convention) -------------
# Keyed by ``DocumentTypeSpec.type_key``. Values are semantic scopes the
# narrative-context filter uses to gate future events out of documents whose
# author (a physician / nurse at a specific point in time) could not
# legitimately know them:
#
#   "day_of_stub" — day-scoped; writing_day = ctx.day_index. progress_note /
#                   nursing_shift_note fire once per calendar day, and the
#                   stub carries the day. operative_note / procedure_note
#                   are also stub-day-scoped (the narrative pass sets
#                   day_index = procedure start day).
#   "admission"   — written at admission or during a single-day encounter;
#                   writing_day = 0. Covers admission_hp / ed_note /
#                   ed_triage_note / admission_care_plan /
#                   admission_nursing_assessment / outpatient_soap /
#                   health_checkup_report.
#   "whole_stay"  — written at discharge / referral / death; writing_day =
#                   None (no temporal filter — the writer legitimately sees
#                   the full admission timeline). Covers discharge_summary /
#                   death_certificate / death_discharge_summary /
#                   nursing_discharge_summary / referral_note /
#                   nutrition_care_plan / rehabilitation_plan.
#
# Unknown doc types default to "whole_stay" (safe backward-compat — a new
# doc type gets no leak filter until explicitly categorised here; the pre-
# filter behaviour was whole-stay-only anyway).
_WRITING_DAY_SCOPE: dict[str, str] = {
    # day-of-stub
    "progress_note": "day_of_stub",
    "nursing_shift_note": "day_of_stub",
    "operative_note": "day_of_stub",
    "procedure_note": "day_of_stub",
    # admission / single-day
    "admission_hp": "admission",
    "admission_nursing_assessment": "admission",
    "admission_care_plan": "admission",
    "ed_note": "admission",
    "ed_triage_note": "admission",
    "outpatient_soap": "admission",
    "health_checkup_report": "admission",
    # whole-stay (discharge / referral / death)
    "discharge_summary": "whole_stay",
    "death_certificate": "whole_stay",
    "death_discharge_summary": "whole_stay",
    "nursing_discharge_summary": "whole_stay",
    "referral_note": "whole_stay",
    "nutrition_care_plan": "whole_stay",
    "rehabilitation_plan": "whole_stay",
}
