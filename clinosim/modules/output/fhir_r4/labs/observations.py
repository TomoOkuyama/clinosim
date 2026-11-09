"""FHIR R4 lab + vital-sign Observation builders (FA-1 Phase 13).

Canonical numeric Observation resources: per-order lab values (via
_build_lab_observation helper) and per-encounter vital signs. Microbiology,
nursing flowsheets, and Immunization were split out in PR3 into
fhir_r4/labs/microbiology.py / fhir_r4/procedures/nursing.py / fhir_r4/procedures/immunization.py
respectively. The ctx-taking builder imports the shared BundleContext
from _fhir_common, so this module never imports back through the adapter
(no cycle).
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from typing import Any

from clinosim.codes import display as registry_display
from clinosim.codes import get_system_uri
from clinosim.codes.loinc import loinc_coding
from clinosim.codes.snomed import snomed_for
from clinosim.codes.ucum import ucum_quantity
from clinosim.countries import lang_for
from clinosim.locale.i18n import t
from clinosim.locale.loader import lab_display, lab_result_display, oxygen_device_label
from clinosim.locale.localized import localized_field
from clinosim.modules._shared import get_attr_or_key, is_jp, sanitize_id_token
from clinosim.modules.observation.engine import medications_in_effect
from clinosim.modules.observation.pediatric_ranges import (
    PediatricVitalRange,
    age_in_completed_months,
    age_independent_vital_range_text,
    pediatric_vital_range,
    pediatric_vital_range_text,
)
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.labs._reference_ranges import (
    BP_DIASTOLIC,
    BP_SYSTOLIC,
    STANDALONE_VITAL_SIGNS,
    BloodPressureComponentReferenceRange,
)
from clinosim.modules.output.fhir_r4.labs.coding_strategy import select_lab_coding_strategy, uncoded_analyte_display
from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
    LAB_OBSERVATION_KEY_SYSTEM,
    _lab_observation_structural_key,
    lab_observation_id,
)
from clinosim.modules.output.fhir_r4.labs.service_request import build_panel_counter, order_to_sr_id
from clinosim.modules.output.fhir_r4.lib.common import (
    build_reference_range,
    dual_slot_concept,
    english_display_concept,
    entry,
    survey_category,
)
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.fhir_time import to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)
from clinosim.modules.output.fhir_r4.lib.jp_profiles import (
    JP_OBSERVATION_COMMON_PROFILE,
    JP_OBSERVATION_LAB_RESULT_PROFILE,
)
from clinosim.types.encounter import Order, OrderType


def _o(order: Any, name: str, default: Any = None) -> Any:
    """Dual-access helper: dataclass attribute OR dict key (production path)."""
    return get_attr_or_key(order, name, default)


# === Issue #854 Bucket A row 4 (PR-obs-vs): opaque vital-sign Observation.id ===
# Same pattern as PR #357 / #863 / #867 / #868 / #869 / #878 (lab Observation).
#
# vs-* Observations are emitted from 4 distinct code paths in this module —
# per-parameter vitals (heart rate / temp / spo2 / RR), the BP-panel
# consolidated Observation, the AVPU "loc" Observation, and the
# supplemental-oxygen "o2" Observation. All 4 share the same
# ``{encounter_id or patient_id}-{index:04d}-{suffix}`` structural key
# body (pre-#854 id without the ``vs-`` prefix) so a single resolver +
# a single ``VITAL_SIGN_OBSERVATION_KEY_SYSTEM`` cover every emit site.
#
# PUBLIC constants so downstream readers (identifier[] round-trip,
# future audit tooling) can import them for identifier-based lookup
# without string-parsing the (now opaque) ``.id``.
VITAL_SIGN_OBSERVATION_ID_PREFIX = "vs-"
VITAL_SIGN_OBSERVATION_KEY_SYSTEM = structural_key_system("vital-sign-observation-key")


def _resolve_vital_sign_observation_id(structural_key: str) -> str:
    """Return the FHIR Observation.id for a vital-sign observation.

    Shape: ``vs-{sha256(structural_key)[:12]}`` = 15 chars, fixed. The
    ``vs-`` prefix retains the human-recognisable identity (URLs like
    ``/Observation/vs-<hex>`` read as a vital-sign Observation at a
    glance) — consistent with the sibling resolvers introduced in
    PR #863 / #867 / #868 / #869 / #878.

    Structural key = pre-#854 vs-* id body (without ``vs-`` prefix):
        ``{encounter_id or patient_id}-{index:04d}-{suffix}``
    where ``suffix`` is one of ``{sanitize_id_token(field), bp-panel,
    loc, o2}``. The 4 emit sites in this module all funnel through this
    resolver so a future format change ripples through a single call
    site (PR-90 silent-no-op defense).

    The compound structural key is preserved on ``Observation.identifier[]``
    via :func:`wrap_as_identifier` under
    :data:`VITAL_SIGN_OBSERVATION_KEY_SYSTEM` for round-trip.
    """
    return derive_opaque_id(VITAL_SIGN_OBSERVATION_ID_PREFIX, structural_key)


# Questionnaire total scores scheduled through the lab pipeline (chronic_followup
# labs_quarterly). They are instrument scores, so FHIR category is survey and no
# laboratory referenceRange applies.
_QUESTIONNAIRE_SCORE_ANALYTES = frozenset({"PHQ-9", "GAD-7", "C-SSRS"})


def lab_observation_coding(lab_name: str, order: dict, result: dict, country: str) -> tuple[list[dict], str]:
    """A lab result's ``code.coding`` and ``code.text``.

    Shared with the single-test DiagnosticReport (Issue #2586) so a report
    is titled exactly like the Observation it carries.
    """
    _strategy = select_lab_coding_strategy(lab_name, country)
    _strategy_kwargs: dict[str, Any] = {"lab_name": lab_name, "order": order, "result": result, "country": country}
    codings = _strategy.emit_codings(**_strategy_kwargs)
    _localcode = _strategy.emit_localcode_coding(**_strategy_kwargs)
    if _localcode is not None:
        codings.append(_localcode)
    # Issue #777: `code.text` should carry a human-readable primary label,
    # not the standard-code display (which for CoreLabo_CS is an English
    # abbreviation like "AST" / "Na"). The LocalCode_CS coding is authored
    # specifically for display (e.g. "AST(GOT)" / "ナトリウム(Na)") and is
    # the JP Core / JP-CLINS convention: `.text` reflects the LocalCode's
    # display when present, otherwise falls through to the first coding's
    # display (pre-fix behaviour preserved for cohorts / countries without
    # a LocalCode coding).
    if _localcode is not None and _localcode.get("display"):
        display_name = _localcode["display"]
    elif codings and not (is_jp(country) and codings[0].get("system") == get_system_uri("loinc")):
        display_name = codings[0]["display"]
    else:
        # No JP code (only the English LOINC interop coding, Issue #2300) or
        # no standard code at all (Issue #2138): the analyte name, in Japanese on JP.
        display_name = uncoded_analyte_display(lab_name, lang_for(country))
        # Issue #3031: an analyte the lab table does not list is named by its
        # LOINC code's label in the output language ("Anion gap" -> アニオンギャップ).
        _loinc = (
            str(codings[0].get("code") or "") if codings and codings[0].get("system") == get_system_uri("loinc") else ""
        )
        if _loinc and not lab_display(lab_name, lang_for(country), fallback=""):
            _named = registry_display("loinc", _loinc, lang_for(country))
            display_name = _named if _named and _named != _loinc else display_name
    return (codings, display_name)


def _build_lab_observation(
    order: dict,
    result: dict,
    patient_id: str,
    index: int,
    country: str,
    patient_sex: str = "",
    encounter_id: str = "",
    patient_medications: Any = None,
    patient_age: int | None = None,
) -> dict | None:
    """Build FHIR Observation resource for a lab result."""
    value = result.get("value")
    if value is None:
        return None

    # Prefer the result's canonical analyte name (stat/serial/alias resolved upstream)
    # over the raw order label, so the code mapping resolves (AD-55).
    lab_name = result.get("lab_name") or order.get("display_name", "Unknown")
    country_code = "JP" if is_jp(country) else "US"

    # PR 1 (JP-CLINS lab coding migration): route through the strategy
    # dispatcher. In PR 1 the classifier returns LEGACY_JSLM (JP) /
    # LEGACY_LOINC (US) for every analyte, so emit_codings reproduces
    # the pre-refactor inline emit exactly (byte-identical guarantee).
    # emit_localcode_coding returns None on every strategy in PR 1 —
    # PR 3 will begin activating LocalCode emission on the CoreLabo /
    # Uncoded paths without protocol churn.
    codings, display_name = lab_observation_coding(lab_name, order, result, country)

    # encounter_id must be non-empty: the production path always provides
    # ctx.primary_enc_id, and it participates in the opaque-id structural key
    # (see ``_lab_observation_structural_key``) so the DR.result[] emit site
    # can recompute the same Observation.id from (enc_id, idx). A patient_id
    # fallback would silently produce a divergent id and break DR.result[]
    # linkage (PR-90 silent-no-op class).
    assert encounter_id, (
        "_build_lab_observation: encounter_id must be non-empty. "
        "All call sites pass ctx.primary_enc_id which is validated before the loop."
    )
    # feedback FB-F6: 特定 LOINC は対応標準 profile を要求。
    # LOINC 39156-5 (BMI) → hl7.org/.../bmi、8480-6/8462-4 (BP) → .../bp。
    # JP コホートも JP Core LabResult + 該当 vital profile を stacking 可能。
    _extra_profiles: list[str] = []
    if lab_name == "BMI":  # health-checkup BMI (Issue #2300: canonical name, LOINC 39156-5 coding)
        _extra_profiles.append("http://hl7.org/fhir/StructureDefinition/bmi")
    # BP 個別 obs は bp profile が component 構造を要求するため、
    # 別 Observation で発行される limitation あり(TODO: 将来 combined 85354-9)。
    # ここでは profile 付与を保留、TODO として cycle 9 に持越し。

    _profiles: list[str] = []
    if is_jp(country):
        _profiles.append(JP_OBSERVATION_LAB_RESULT_PROFILE)
    _profiles.extend(_extra_profiles)

    # Issue #854 Bucket A row 4 (PR-obs-lab): opaque Observation.id.
    # ``lab_observation_id(enc, idx)`` returns ``lab-<12hex>`` — same
    # resolver called by ``DiagnosticReport.result[]`` emit so the reference
    # edge stays byte-consistent. The compound structural key
    # ``{encounter_id}-{idx:04d}`` (pre-#854 id body) is preserved verbatim
    # on ``identifier[]`` under ``LAB_OBSERVATION_KEY_SYSTEM`` so consumers
    # can recover the source-path metadata without string-parsing the id.
    _lab_obs_structural_key = _lab_observation_structural_key(encounter_id, index)
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": lab_observation_id(encounter_id, index),
        "identifier": [wrap_as_identifier(_lab_obs_structural_key, LAB_OBSERVATION_KEY_SYSTEM)],
        # chain #2: JP Core Observation_LabResult profile.
        # feedback FB-F6: 該当 LOINC の standard profile も stack 追加。
        **({"meta": {"profile": _profiles}} if _profiles else {}),
        "status": "final",
        "category": survey_category(lang_for(country))
        if lab_name in _QUESTIONNAIRE_SCORE_ANALYTES
        else [dual_slot_concept("hl7-observation-category", "laboratory", lang_for(country))],
        "code": {"coding": codings, "text": display_name} if codings else {"text": display_name},
        "subject": patient_ref(patient_id),
        # Session-98 F11 fix. `effectiveDateTime` on a lab Observation is
        # the *sample collection* time (FHIR spec: "The time or time-period
        # the observed value is asserted as being true"); `issued` is when
        # the report becomes available in the chart. Pre-fix we wrote the
        # RESULT time into `effectiveDateTime`, which for late-ED lab
        # orders (encounter ends 23:XX, result at 00:XX next day) produced
        # observations dated AFTER the parent encounter's period.end — 74
        # such Obs on JP p=10000 seed=500. Fix: prefer the parent Order's
        # `ordered_datetime` (a close proxy for collection time — sample
        # is drawn shortly after order) and expose the result availability
        # via `issued`.
        "effectiveDateTime": order.get("ordered_datetime") or result.get("result_datetime", ""),
        "issued": result.get("result_datetime", ""),
    }

    if isinstance(value, (int, float)):
        # Issue #3011: in the country's reporting unit (JP CRP mg/dL); the
        # reference range below is stated in the same unit.
        from clinosim.modules.observation.engine import reported_lab_value

        value, unit_str = reported_lab_value(lab_name, value, str(result.get("unit", "") or ""), country)
        # #323 FHIR R4 ele-1 は空文字列 field を禁止。unit が
        # 未設定時(unit_str == "")は unit / code / system 全て omit
        # (v6.1 で 44 件 error 発火)。value のみ emit する。
        resource["valueQuantity"] = ucum_quantity(value, unit_str) if unit_str else {"value": value}
    else:
        # Issue #3031: a qualitative result in the output language.
        resource["valueString"] = str(lab_result_display(value, lang_for(country)))

    # Reference range (JP: JCCLS共用基準範囲). A health-checkup result is
    # judged against the checkup criterion (保健指導判定値) stored on the result
    # (reference_range_lab.yaml checkup_ranges), not the general range, so it
    # carries that text and its interpretation follows the stored flag
    # (Issue #2300).
    ref_range: list[dict[str, Any]] | None
    if order.get("clinical_intent") == "health_checkup":
        _checkup_text = str(result.get("reference_range") or "")
        ref_range = [{"text": _checkup_text}] if _checkup_text else None
    else:
        ref_range = build_reference_range(
            lab_name, patient_sex, country_code, medications=patient_medications, age=patient_age
        )
    if ref_range:
        resource["referenceRange"] = ref_range

    # Interpretation — recompute from value vs reference range when possible
    # (ensures consistency per FHIR spec: both must be consistent when provided).
    # Fall back to flag-based mapping for non-numeric or no-range cases.
    flag = result.get("flag")
    interp_map = {
        "H": "H",
        "L": "L",
        "H*": "HH",
        "L*": "LL",
        "critical": "AA",
    }
    coded: str | None = None
    if isinstance(value, (int, float)) and ref_range:
        # Find normal range (type=normal or unlabeled first entry); a
        # therapeutic range, present only for patients on the matching drug,
        # takes precedence (Issue #2205).
        normal_rng = None
        for rng in ref_range:
            tc = (rng.get("type") or {}).get("coding", [{}])[0].get("code", "")
            if tc == "therapeutic":
                normal_rng = rng
                break
            if (tc == "normal" or not tc) and normal_rng is None:
                normal_rng = rng
        # A text-only range (no bounds) cannot judge the value: keep the
        # stored flag (health-checkup criterion text, Issue #2300).
        if normal_rng and (normal_rng.get("low") or normal_rng.get("high")):
            low_v = (normal_rng.get("low") or {}).get("value")
            high_v = (normal_rng.get("high") or {}).get("value")
            is_critical = flag in ("H*", "L*", "critical")
            out_low = low_v is not None and value < low_v
            out_high = high_v is not None and value > high_v
            if is_critical and out_low:
                coded = "LL"
            elif is_critical and out_high:
                coded = "HH"
            elif is_critical:
                coded = "AA"
            elif out_low:
                coded = "L"
            elif out_high:
                coded = "H"
            else:
                coded = "N"
    if coded is None:
        coded = interp_map.get(flag) if flag else "N"
    if coded is None:
        coded = "N"
    resource["interpretation"] = [dual_slot_concept("hl7-observation-interpretation", coded, lang_for(country))]

    # Encounter reference (use order's encounter_id, fallback to primary)
    enc_ref = order.get("encounter_id", "") or encounter_id
    if enc_ref:
        resource["encounter"] = encounter_ref(enc_ref)

    # Performer (lab technician or ordering physician)
    performer_id = result.get("performed_by", "") or order.get("ordered_by", "")
    if performer_id:
        resource["performer"] = [{"reference": f"Practitioner/{performer_id}"}]

    # C5-21 (Chain 2): Observation.method for lab. clinosim's synthetic
    # analytes are all produced on an automated bench analyzer path (there
    # is no manual titration / immunofluorescence / HPLC branch in the
    # data-generation pipeline). Text-only CodeableConcept per FHIR R4
    # (system+code omitted intentionally — no authoritative universal
    # method-code exists for "automated bench analyzer" that fits every
    # analyte). Mirrors Coverage.type text-only precedent.
    _method_text = t("fhir_obs_text.automated_method", lang_for(country))
    resource["method"] = {"text": _method_text}

    return resource


def _build_bp_component(
    spec: BloodPressureComponentReferenceRange,
    value: float,
    country: str,
    pediatric: PediatricVitalRange | None = None,
) -> dict[str, Any]:
    """Build one `component[]` entry inside the BP-panel Observation (#210).

    Encodes the LOINC code (systolic 8480-6 / diastolic 8462-4),
    valueQuantity in mmHg, the paired referenceRange (normal + critical),
    and the derived interpretation flag. Reference-range and
    interpretation ranges match the pre-#210 per-Observation shape so
    downstream flag semantics stay identical.
    """
    display = localized_field(spec, "display", lang_for(country))
    unit = "mm[Hg]"
    low, high, crit_low, crit_high, normal_text = _vital_bounds(
        spec.normal_low, spec.normal_high, spec.critical_low, spec.critical_high, pediatric, country
    )
    return {
        "code": {
            # Issue #3026: English LOINC display on the coding, the label in text.
            "coding": [_vital_loinc_coding(spec.loinc, localized_field(spec, "display", "en"))],
            "text": display,
        },
        "valueQuantity": ucum_quantity(value, unit),
        "referenceRange": _vital_reference_ranges(
            low, high, crit_low, crit_high, unit, normal_text, country, critical_bounds_first=True
        ),
        "interpretation": [
            dual_slot_concept(
                "hl7-observation-interpretation",
                _vital_interpretation(value, low, high, crit_low, crit_high),
                lang_for(country),
            )
        ],
    }


def _vital_bounds(
    normal_low: float,
    normal_high: float,
    critical_low: float | None,
    critical_high: float | None,
    pediatric: PediatricVitalRange | None,
    country: str,
) -> tuple[float, float, float | None, float | None, str]:
    """``(low, high, critical_low, critical_high, normal text)`` of a vital sign:
    the child's age-band range when one applies (Issue #2872), else the adult range."""
    if pediatric is not None:
        return (
            pediatric.low,
            pediatric.high,
            pediatric.critical_low,
            pediatric.critical_high,
            pediatric_vital_range_text(pediatric, lang_for(country)),
        )
    adult_text = t("fhir_obs_text.normal_adult_range", lang_for(country))
    return normal_low, normal_high, critical_low, critical_high, adult_text


def _vital_interpretation(
    value: float, low: float, high: float, critical_low: float | None, critical_high: float | None
) -> str:
    """LL / HH at or beyond a critical bound, L / H outside the normal range, else N."""
    if critical_low is not None and value <= critical_low:
        return "LL"
    if critical_high is not None and value >= critical_high:
        return "HH"
    if value < low:
        return "L"
    if value > high:
        return "H"
    return "N"


def _vital_loinc_coding(code: str, fallback_en: str) -> dict[str, Any]:
    """A vital-sign LOINC Coding with the English canonical display (Issue #3026)."""
    coding: dict[str, Any] = {"system": get_system_uri("loinc"), "code": code}
    display = fallback_en or loinc_coding(code, "en").get("display", "")
    if display:
        coding["display"] = display
    return coding


def _range_meaning(code: str, country: str) -> dict[str, Any]:
    # Issue #3026: English display on the HL7 coding, the label in ``text``.
    return english_display_concept("hl7-referencerange-meaning", code, lang_for(country))


def _vital_reference_ranges(
    low: float,
    high: float,
    critical_low: float | None,
    critical_high: float | None,
    unit: str,
    normal_text: str,
    country: str,
    *,
    critical_bounds_first: bool,
) -> list[dict[str, Any]]:
    """The normal range, then the critical (panic) range when it has a bound.

    ``critical_bounds_first`` keeps each emitter's historical key order
    (BP components put low / high before type / text in the critical range).
    """
    ranges: list[dict[str, Any]] = [
        {
            "low": ucum_quantity(low, unit),
            "high": ucum_quantity(high, unit),
            "type": _range_meaning("normal", country),
            "text": normal_text,
        }
    ]
    if critical_low is None and critical_high is None:
        return ranges
    bounds: dict[str, Any] = {}
    if critical_low is not None:
        bounds["low"] = ucum_quantity(critical_low, unit)
    if critical_high is not None:
        bounds["high"] = ucum_quantity(critical_high, unit)
    crit_text = t("fhir_obs_text.critical_range", lang_for(country))
    meaning = {"type": _range_meaning("treatment", country), "text": crit_text}
    ranges.append({**bounds, **meaning} if critical_bounds_first else {**meaning, **bounds})
    return ranges


def _build_vital_observations(
    vs: dict,
    patient_id: str,
    index: int,
    country: str = "US",
    encounter_id: str = "",
    *,
    birth_date: Any = None,
    age_years: int | None = None,
) -> list[dict]:
    """Build FHIR Observation resources for vital signs (one per parameter).

    Blood-pressure special case (#210, 2026-07-17): systolic (LOINC 8480-6)
    and diastolic (LOINC 8462-4) are consolidated into a single Observation
    with `code = LOINC 85354-9` (BP panel) and two `component[]` entries.
    The FHIR base "bp" profile (auto-applied by HAPI on any Observation
    whose `code` is a BP-panel LOINC) requires exactly this shape; emitting
    the two components as separate top-level Observations produced ~14.5k
    ``component:SystolicBP min=1`` / ``component:DiastolicBP min=1`` /
    ``BPCode: magic LOINC code 85354-9 required`` errors on the
    fhir-jp-validator 2026-07-17 report (§【最優先 7】).
    """
    entries = []

    # Issue #2872: the patient's age in completed months when the set was
    # measured (from the birth date, else the record's age in years) picks
    # a child's age-band range; ``None`` keeps the adult range.
    age_months = age_in_completed_months(birth_date, vs.get("timestamp"))
    if age_months is None and age_years is not None:
        age_months = int(age_years) * 12

    # Vital-sign reference/critical ranges live in `_reference_ranges.py`
    # (Issue #637 PR-C); iterate the canonical `STANDALONE_VITAL_SIGNS`
    # tuple whose element order matches the pre-refactor `_vital_map`.
    #
    # NOTE: `systolic_bp` / `diastolic_bp` used to appear here as separate
    # Observations; they are now consolidated into a single BP panel
    # Observation emitted at the end of this function (see #210). Reference
    # ranges for the components live in the panel's per-component
    # `referenceRange[]` block, matching the FHIR base "bp" profile shape.
    for spec in STANDALONE_VITAL_SIGNS:
        field = spec.field
        loinc = spec.loinc
        unit = spec.unit
        low = spec.normal_low
        high = spec.normal_high
        crit_low = spec.critical_low
        crit_high = spec.critical_high
        offset_sec = spec.time_offset_sec
        display = localized_field(spec, "display", lang_for(country))
        value = vs.get(field)
        if value is None:
            continue

        # Issue #854 Bucket A row 4 (PR-obs-vs): opaque vital-sign Observation.id.
        # sanitize_id_token normalizes the vital field name (underscores
        # forbidden in FHIR R4 ids); ``systolic_bp`` → ``systolic-bp`` etc.
        # This normalized token participates in the structural key so
        # equivalent inputs produce equivalent opaque ids.
        _vs_structural_key = f"{encounter_id or patient_id}-{index:04d}-{sanitize_id_token(field)}"
        obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": _resolve_vital_sign_observation_id(_vs_structural_key),
            "identifier": [wrap_as_identifier(_vs_structural_key, VITAL_SIGN_OBSERVATION_KEY_SYSTEM)],
            # chain #2: JP Core Observation_Common profile for vitals.
            **({"meta": {"profile": [JP_OBSERVATION_COMMON_PROFILE]}} if is_jp(country) else {}),
            "status": "final",
            "category": [dual_slot_concept("hl7-observation-category", "vital-signs", lang_for(country))],
            "code": {
                "coding": [_vital_loinc_coding(loinc, localized_field(spec, "display", "en"))],
                "text": display,
            },
            "subject": patient_ref(patient_id),
            "valueQuantity": ucum_quantity(value, unit),
        }
        # Add timestamp with per-field offset (BP/HR same, Temp +30s, RR +60s, SpO2 +5s)
        timestamp = vs.get("timestamp")
        if timestamp:
            try:
                from datetime import datetime as _dt
                from datetime import timedelta as _td

                base_dt = _dt.fromisoformat(str(timestamp).replace("Z", "+00:00").split("+")[0])
                shifted = base_dt + _td(seconds=offset_sec)
                obs["effectiveDateTime"] = shifted.isoformat()
            except (ValueError, TypeError):
                obs["effectiveDateTime"] = to_fhir_datetime(timestamp)

        # Encounter reference
        if encounter_id:
            obs["encounter"] = encounter_ref(encounter_id)

        # Performer (nurse who measured)
        performer_id = vs.get("measured_by", "")
        if performer_id:
            obs["performer"] = [{"reference": f"Practitioner/{performer_id}"}]

        # Reference range — normal range (always) + critical range (when
        # defined); a child is judged against the range for their age
        # (Issue #2872). The interpretation is computed from the same bounds.
        low, high, crit_low, crit_high, range_text = _vital_bounds(
            low, high, crit_low, crit_high, pediatric_vital_range(field, age_months), country
        )
        range_text = age_independent_vital_range_text(field, age_months, lang_for(country)) or range_text
        obs["referenceRange"] = _vital_reference_ranges(
            low, high, crit_low, crit_high, unit, range_text, country, critical_bounds_first=False
        )
        interp_code = _vital_interpretation(value, low, high, crit_low, crit_high)
        obs["interpretation"] = [dual_slot_concept("hl7-observation-interpretation", interp_code, lang_for(country))]

        entries.append(entry(obs))

    # BP panel (#210, 2026-07-17). One Observation with LOINC 85354-9 in
    # `code` and both systolic + diastolic as `component[]` — the exact
    # shape the FHIR base "bp" profile requires (HAPI auto-applies that
    # profile whenever it sees a BP-panel LOINC or its component codes).
    # Emit only when both systolic and diastolic are present in `vs`; a
    # partial (systolic-only or diastolic-only) BP reading is not clinically
    # meaningful and does not appear in real clinosim output today.
    sbp = vs.get("systolic_bp")
    dbp = vs.get("diastolic_bp")
    if sbp is not None and dbp is not None:
        bp_display = t("fhir_obs_text.bp_panel", lang_for(country))
        _bp_structural_key = f"{encounter_id or patient_id}-{index:04d}-bp-panel"
        bp_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": _resolve_vital_sign_observation_id(_bp_structural_key),
            "identifier": [wrap_as_identifier(_bp_structural_key, VITAL_SIGN_OBSERVATION_KEY_SYSTEM)],
            **({"meta": {"profile": [JP_OBSERVATION_COMMON_PROFILE]}} if is_jp(country) else {}),
            "status": "final",
            "category": [dual_slot_concept("hl7-observation-category", "vital-signs", lang_for(country))],
            "code": {
                "coding": [_vital_loinc_coding("85354-9", t("fhir_obs_text.bp_panel", "en"))],
                "text": bp_display,
            },
            "subject": patient_ref(patient_id),
            "component": [
                _build_bp_component(BP_SYSTOLIC, sbp, country, pediatric_vital_range("systolic_bp", age_months)),
                _build_bp_component(BP_DIASTOLIC, dbp, country, pediatric_vital_range("diastolic_bp", age_months)),
            ],
        }
        # Timestamp — BP + HR share the same measurement cycle (offset 0)
        timestamp = vs.get("timestamp")
        if timestamp:
            try:
                from datetime import datetime as _dt

                base_dt = _dt.fromisoformat(str(timestamp).replace("Z", "+00:00").split("+")[0])
                bp_obs["effectiveDateTime"] = base_dt.isoformat()
            except (ValueError, TypeError):
                bp_obs["effectiveDateTime"] = to_fhir_datetime(timestamp)
        if encounter_id:
            bp_obs["encounter"] = encounter_ref(encounter_id)
        performer_id = vs.get("measured_by", "")
        if performer_id:
            bp_obs["performer"] = [{"reference": f"Practitioner/{performer_id}"}]
        entries.append(entry(bp_obs))

    # Consciousness level (AVPU) — Glasgow Coma Scale-related
    loc = vs.get("consciousness_level", "")
    if loc:
        loc_display_map = {
            "A": ("Alert", "248234008"),
            "V": ("Responds to voice", "248236005"),
            "P": ("Responds to pain", "248237001"),
            "U": ("Unresponsive", "422768004"),
        }
        loc_display, loc_snomed = loc_display_map.get(loc, ("Alert", "248234008"))
        display = t(f"fhir_obs_text.avpu_{loc}", "ja") or loc_display if is_jp(country) else loc_display
        _loc_structural_key = f"{encounter_id or patient_id}-{index:04d}-loc"
        loc_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": _resolve_vital_sign_observation_id(_loc_structural_key),
            "identifier": [wrap_as_identifier(_loc_structural_key, VITAL_SIGN_OBSERVATION_KEY_SYSTEM)],
            # chain #2: JP Core Observation_Common profile for vitals.
            **({"meta": {"profile": [JP_OBSERVATION_COMMON_PROFILE]}} if is_jp(country) else {}),
            "status": "final",
            "category": [dual_slot_concept("hl7-observation-category", "vital-signs", lang_for(country))],
            "code": {
                "coding": [
                    {
                        "system": get_system_uri("loinc"),
                        "code": "80288-4",
                        # Issue #384 hotfix wave 4: the actual
                        # fhirserver LOINC 2.82 canonical for 80288-4 is
                        # "Level of consciousness" (simple, no "AVPU"
                        # qualifier, no "score" suffix) — confirmed via
                        # direct SQLite Codes.Description query + curl
                        # against fhirserver. Prior emits were all wrong:
                        #   v25:  "Level of consciousness AVPU"        (SHORTNAME, hardcoded)
                        #   v28:  same (PR #385 yaml-only change did not propagate — hardcoded)
                        #   v29:  "Level of consciousness AVPU score"  (PR #388 wrong-canonical hardcode)
                        # This 4th iteration adopts the ACTUAL fhirserver
                        # canonical. Lesson memorialised in
                        # feedback_fhirserver_actual_canonical_verify.md
                        # (never trust user-report or narrative canonicals
                        # without direct fhirserver measurement).
                        "display": "Level of consciousness",
                    }
                ],
                "text": t("fhir_obs_text.loc_avpu", lang_for(country)),
            },
            "subject": patient_ref(patient_id),
            "valueCodeableConcept": {
                "coding": [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": loc_snomed,
                        # Issue #3026: English SNOMED display; the label in text.
                        "display": loc_display,
                    }
                ],
                "text": display,
            },
        }
        timestamp = vs.get("timestamp")
        if timestamp:
            loc_obs["effectiveDateTime"] = to_fhir_datetime(timestamp)
        if encounter_id:
            loc_obs["encounter"] = encounter_ref(encounter_id)
        # RM-1: forward performer (nurse measured_by) on LOC obs.
        _perf = vs.get("measured_by", "")
        if _perf:
            loc_obs["performer"] = [{"reference": f"Practitioner/{_perf}"}]
        entries.append(entry(loc_obs))

    # Pain score (Issue #2089): LOINC 72514-3, 0-10 numeric rating, reported.
    # Verified via tx.fhir.org $lookup (LOINC 2.83).
    pain = vs.get("pain_score")
    if pain is not None:
        _pain_structural_key = f"{encounter_id or patient_id}-{index:04d}-pain"
        pain_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": _resolve_vital_sign_observation_id(_pain_structural_key),
            "identifier": [wrap_as_identifier(_pain_structural_key, VITAL_SIGN_OBSERVATION_KEY_SYSTEM)],
            **({"meta": {"profile": [JP_OBSERVATION_COMMON_PROFILE]}} if is_jp(country) else {}),
            "status": "final",
            "category": [dual_slot_concept("hl7-observation-category", "vital-signs", lang_for(country))],
            "code": {
                "coding": [
                    {
                        "system": get_system_uri("loinc"),
                        "code": "72514-3",
                        "display": "Pain severity - 0-10 verbal numeric rating [Score] - Reported",
                    }
                ],
                "text": t("fhir_obs_text.pain_nrs", lang_for(country)),
            },
            "subject": patient_ref(patient_id),
            "valueInteger": int(pain),
        }
        timestamp = vs.get("timestamp")
        if timestamp:
            pain_obs["effectiveDateTime"] = to_fhir_datetime(timestamp)
        if encounter_id:
            pain_obs["encounter"] = encounter_ref(encounter_id)
        _perf = vs.get("measured_by", "")
        if _perf:
            pain_obs["performer"] = [{"reference": f"Practitioner/{_perf}"}]
        entries.append(entry(pain_obs))

    # Supplemental oxygen (LOINC 3151-8 = inhaled oxygen flow rate)
    if vs.get("on_supplemental_oxygen"):
        flow = vs.get("oxygen_flow_rate_lpm")
        device = vs.get("oxygen_delivery_device", "")
        _o2_structural_key = f"{encounter_id or patient_id}-{index:04d}-o2"
        o2_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": _resolve_vital_sign_observation_id(_o2_structural_key),
            "identifier": [wrap_as_identifier(_o2_structural_key, VITAL_SIGN_OBSERVATION_KEY_SYSTEM)],
            # chain #2: JP Core Observation_Common profile for vitals.
            **({"meta": {"profile": [JP_OBSERVATION_COMMON_PROFILE]}} if is_jp(country) else {}),
            "status": "final",
            "category": [dual_slot_concept("hl7-observation-category", "vital-signs", lang_for(country))],
            "code": {
                "coding": [
                    {
                        "system": get_system_uri("loinc"),
                        "code": "3151-8",
                        "display": "Inhaled oxygen flow rate",
                    }
                ],
                "text": t("fhir_obs_text.o2_flow", lang_for(country)),
            },
            "subject": patient_ref(patient_id),
        }
        if flow is not None:
            o2_obs["valueQuantity"] = ucum_quantity(flow, "L/min")
        device_code = snomed_for("oxygen_device", str(device)) if device else None
        if device_code:
            # Issue #376: LOINC 8478-0 is "Mean blood pressure" — completely
            # unrelated to oxygen delivery. Verified via NLM Clinical Table +
            # tx.fhir.org $lookup. Correct code for "device / method by which
            # oxygen is delivered" is LOINC 107117-4 "Method of oxygen
            # delivery" (ACTIVE on tx.fhir.org).
            o2_obs["component"] = [
                {
                    "code": {
                        "coding": [
                            {
                                "system": get_system_uri("loinc"),
                                "code": "107117-4",
                                "display": "Method of oxygen delivery",
                            }
                        ],
                    },
                    # Issue #3023: the device concept (SNOMED CT, English
                    # display) with its clinical label in the output language.
                    "valueCodeableConcept": dual_slot_concept(
                        "snomed-ct",
                        device_code,
                        lang_for(country),
                        text=oxygen_device_label(str(device), lang_for(country)) or None,
                    ),
                }
            ]
        timestamp = vs.get("timestamp")
        if timestamp:
            o2_obs["effectiveDateTime"] = to_fhir_datetime(timestamp)
        if encounter_id:
            o2_obs["encounter"] = encounter_ref(encounter_id)
        # RM-1: forward performer on O2 obs.
        _perf = vs.get("measured_by", "")
        if _perf:
            o2_obs["performer"] = [{"reference": f"Practitioner/{_perf}"}]
        entries.append(entry(o2_obs))

    return entries


def _date_of(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def _medications_on_result_day(
    home_medications: Any, medication_orders: list, admission_date: date | None, result_datetime: Any
) -> list[Any]:
    result_date = _date_of(result_datetime)
    day = (result_date - admission_date).days if result_date and admission_date else None
    return medications_in_effect(home_medications, medication_orders, admission_date, day)


def _bb_labs(ctx: BundleContext) -> list[dict[str, Any]]:
    """Build FHIR Observation resources for lab results.

    Each lab Observation carries a ``basedOn`` reference to the ServiceRequest
    for the originating Order. Panel member Observations all share the panel
    SR id (e.g. 4 CBC components → all reference sr-enc1-CBC-1). Stand-alone
    Observations reference their own SR.

    Dual-access: supports both Order dataclass objects (test harness and
    future direct-object pipeline) and JSON-deserialized dicts (production
    CIF path via json.load). ``basedOn`` is now populated on BOTH paths via
    the dict-compatible ``build_panel_counter`` + ``order_to_sr_id`` helpers
    (Fix 2 — closes the silent basedOn omission on production dict path).
    """
    orders = ctx.record.get("orders", []) or []

    # Build panel counter from all lab orders (dataclass OR dict — both accepted
    # after Fix 1 refactored build_panel_counter to use _o dual-access).
    lab_order_objects = [o for o in orders if _o(o, "order_type") in (OrderType.LAB, "lab")]
    panel_counter = build_panel_counter(lab_order_objects)

    # Issue #2293: the therapeutic reference range follows the same
    # in-effect medication decision the simulator used to generate and flag
    # the result (home medications plus drugs started in hospital past their
    # loading period).
    home_medications = (ctx.patient_data or {}).get("current_medications")
    medication_orders = [o for o in orders if _o(o, "order_type") in (OrderType.MEDICATION, "medication")]
    encounters = ctx.record.get("encounters") or []
    admission_date = _date_of(_o(encounters[0], "admission_datetime")) if encounters else None

    out: list[dict[str, Any]] = []
    for i, order in enumerate(orders):
        # Single, shared filter condition (dual-access via _o) — a prior
        # version of this loop maintained two independently-written
        # conditions, one per isinstance branch, which could silently drift
        # apart. Only the dict/dataclass -> plain-dict conversion below
        # still needs to branch, since dataclasses.asdict() only applies to
        # the dataclass path.
        if _o(order, "order_type") not in (OrderType.LAB, "lab"):
            continue
        result_data = _o(order, "result")
        if not result_data:
            continue
        if _o(order, "display_name", "") == "Type_and_screen":
            continue  # Issue #2587: emitted as ABO / RhD / antibody screen by blood_type.py

        if isinstance(order, Order):
            # Order dataclass path (tests + future direct-object pipeline).
            order_dict = dataclasses.asdict(order)
            result_dict: dict[str, Any] = order_dict.get("result") or {}
        else:
            # JSON-deserialized dict path (production CIF loaded from json.load).
            order_dict = order
            result_dict = result_data if isinstance(result_data, dict) else {}
        # Computable for both dataclass and dict via dict-compatible panel_counter.
        sr_id: str | None = order_to_sr_id(order, panel_counter)

        obs = _build_lab_observation(
            order_dict,
            result_dict,
            ctx.patient_id,
            i,
            ctx.country,
            ctx.patient_sex,
            ctx.primary_enc_id,
            patient_medications=_medications_on_result_day(
                home_medications, medication_orders, admission_date, result_dict.get("result_datetime")
            ),
            patient_age=(ctx.patient_data or {}).get("age"),
        )
        if obs:
            if sr_id is not None:
                obs["basedOn"] = [{"reference": f"ServiceRequest/{sr_id}"}]
            out.append(obs)
    return out
