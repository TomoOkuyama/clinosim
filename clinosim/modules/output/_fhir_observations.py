"""FHIR R4 Observation-family resource builders (FA-1 Phase 13).

Laboratory + vital-sign Observations, nursing-flowsheet Observations
(NEWS2/GCS/Braden/Morse/ADL/I&O), microbiology (Specimen + Observation +
DiagnosticReport), and Immunization. Extracted verbatim from ``fhir_r4_adapter``;
the ctx-taking builders import the shared BundleContext from _fhir_common, so
this module never imports back through the adapter (no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping
from clinosim.modules.output._fhir_common import (
    BundleContext,
    _build_reference_range,
    _entry,
    _loinc_coding,
    _micro_coding,
    _survey_category,
)
from clinosim.modules.output._fhir_localization import (
    _CATEGORY_DISPLAY_JA,
    _INTERPRETATION_DISPLAY_JA,
    _localize_display,
    _localize_interp,
)

_SUSCEPTIBILITY_DISPLAY = {
    "S": {"en": "Susceptible", "ja": "感性"},
    "I": {"en": "Intermediate", "ja": "中間"},
    "R": {"en": "Resistant", "ja": "耐性"},
}


def _bb_microbiology(ctx: BundleContext) -> list[dict]:
    """Microbiology cultures → Specimen + Observation(s) + DiagnosticReport (AD-55)."""
    cultures = ctx.record.get("microbiology") or []
    if not cultures:
        return []
    lang = "ja" if ctx.country == "JP" else "en"
    subject = {"reference": f"Patient/{ctx.patient_id}"}
    enc_ref = {"reference": f"Encounter/{ctx.primary_enc_id}"} if ctx.primary_enc_id else None
    lab_category = [{"coding": [{
        "system": get_system_uri("hl7-observation-category"),
        "code": "laboratory", "display": "Laboratory",
    }]}]
    out: list[dict] = []

    for i, mb in enumerate(cultures):
        base = f"{ctx.primary_enc_id or ctx.patient_id}-{i}"
        spec_id = f"spec-{base}"
        specimen: dict[str, Any] = {"resourceType": "Specimen", "id": spec_id, "subject": subject}
        if mb.get("specimen_snomed"):
            specimen["type"] = {"coding": [_micro_coding("snomed-ct", mb["specimen_snomed"], lang)]}
        if mb.get("collected_datetime"):
            specimen["collection"] = {"collectedDateTime": mb["collected_datetime"]}
        out.append(specimen)

        culture_loinc = mb.get("test_loinc", "")
        culture_code = ({"coding": [_micro_coding("loinc", culture_loinc, lang)]}
                        if culture_loinc else {"text": "Culture"})
        result_refs: list[dict] = []

        org_id = f"mb-org-{base}"
        org_obs: dict[str, Any] = {
            "resourceType": "Observation", "id": org_id, "status": "final",
            "category": lab_category, "code": culture_code, "subject": subject,
            "specimen": {"reference": f"Specimen/{spec_id}"},
        }
        if enc_ref:
            org_obs["encounter"] = enc_ref
        if mb.get("reported_datetime"):
            org_obs["effectiveDateTime"] = mb["reported_datetime"]
        if mb.get("growth") and mb.get("organism_snomed"):
            org_obs["valueCodeableConcept"] = {
                "coding": [_micro_coding("snomed-ct", mb["organism_snomed"], lang)]
            }
            if mb.get("quantitation"):
                org_obs["note"] = [{"text": mb["quantitation"]}]
        else:
            org_obs["valueString"] = "発育なし" if lang == "ja" else "No growth"
        out.append(org_obs)
        result_refs.append({"reference": f"Observation/{org_id}"})

        for j, sus in enumerate(mb.get("susceptibilities") or []):
            interp = sus.get("interpretation", "")
            disp = _SUSCEPTIBILITY_DISPLAY.get(interp, {})
            sus_id = f"mb-sus-{base}-{j}"
            sus_obs: dict[str, Any] = {
                "resourceType": "Observation", "id": sus_id, "status": "final",
                "category": lab_category,
                "code": {"coding": [_micro_coding("loinc", sus.get("antibiotic_loinc", ""), lang)]},
                "subject": subject,
                "specimen": {"reference": f"Specimen/{spec_id}"},
                "valueCodeableConcept": {"coding": [{
                    "system": get_system_uri("hl7-observation-interpretation"),
                    "code": interp,
                    "display": disp.get(lang, disp.get("en", interp)),
                }]},
            }
            if enc_ref:
                sus_obs["encounter"] = enc_ref
            out.append(sus_obs)
            result_refs.append({"reference": f"Observation/{sus_id}"})

        report: dict[str, Any] = {
            "resourceType": "DiagnosticReport", "id": f"dr-mb-{base}", "status": "final",
            "category": [{"coding": [{
                "system": get_system_uri("hl7-diagnostic-service-section"),
                "code": "MB", "display": "Microbiology",
            }]}],
            "code": culture_code, "subject": subject,
            "specimen": [{"reference": f"Specimen/{spec_id}"}],
            "result": result_refs,
        }
        if enc_ref:
            report["encounter"] = enc_ref
        if mb.get("reported_datetime"):
            report["effectiveDateTime"] = mb["reported_datetime"]
        out.append(report)

    return out


def _build_nursing_observations(ctx: BundleContext) -> list[dict]:
    """Build FHIR Observation resources for nursing flowsheet data (category=survey).

    Emits observations for:
    - NEWS2 score (no authoritative LOINC — code.text only)
    - GCS total (LOINC 9269-2)
    - Braden scale total (LOINC 38227-5)
    - Morse fall risk total (LOINC 59460-6) with fall_risk_level in interpretation
    - Barthel index total (LOINC 96761-2)
    - Fluid intake total 24h (LOINC 9108-2)
    - Urine output 24h (LOINC 9192-6)
    - Fluid output total 24h (LOINC 9262-7)
    """
    enc = ctx.primary_enc_id
    lang = "ja" if ctx.country == "JP" else "en"
    subject: dict[str, Any] = {"reference": f"Patient/{ctx.patient_id}"}
    enc_ref: dict[str, Any] | None = (
        {"reference": f"Encounter/{enc}"} if enc else None
    )
    out: list[dict] = []

    def _obs_base(obs_id: str, effective: str | None) -> dict[str, Any]:
        """Return the shared skeleton of a survey Observation."""
        resource: dict[str, Any] = {
            "resourceType": "Observation",
            "id": obs_id,
            "status": "final",
            "category": _survey_category(),
            "subject": subject,
        }
        if enc_ref:
            resource["encounter"] = enc_ref
        if effective:
            resource["effectiveDateTime"] = effective
        return resource

    # --- Vital signs: NEWS2 and GCS ---
    for i, vs in enumerate(ctx.record.get("vital_signs") or []):
        ts: str | None = vs.get("timestamp")
        effective = ts if isinstance(ts, str) else (str(ts) if ts is not None else None)

        news2 = vs.get("news2_score")
        if news2 is not None:
            obs = _obs_base(f"news2-{enc or ctx.patient_id}-{i}", effective)
            # NEWS2 has no authoritative LOINC — emit code.text only (per AD brief)
            obs["code"] = {"text": "NEWS2"}
            obs["valueInteger"] = int(news2)
            out.append(obs)

        gcs = vs.get("gcs_score")
        if gcs is not None:
            obs = _obs_base(f"gcs-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("9269-2", lang)],
                "text": code_lookup("loinc", "9269-2", lang) or "Glasgow coma score total",
            }
            obs["valueInteger"] = int(gcs)
            out.append(obs)

    # --- Nursing risk assessments: Braden and Morse ---
    for i, nra in enumerate(ctx.record.get("nursing_risk_assessments") or []):
        nra_date: str | None = nra.get("date")
        effective = nra_date if isinstance(nra_date, str) else (
            str(nra_date) if nra_date is not None else None
        )

        braden = nra.get("braden_total")
        if braden is not None:
            obs = _obs_base(f"braden-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("38227-5", lang)],
                "text": code_lookup("loinc", "38227-5", lang) or "Braden scale total score",
            }
            obs["valueInteger"] = int(braden)
            out.append(obs)

        morse = nra.get("morse_total")
        if morse is not None:
            obs = _obs_base(f"morse-{enc or ctx.patient_id}-{i}", effective)
            morse_text = (
                code_lookup("loinc", "59460-6", lang) or "Fall risk total [Morse Fall Scale]"
            )
            obs["code"] = {
                "coding": [_loinc_coding("59460-6", lang)],
                "text": morse_text,
            }
            obs["valueInteger"] = int(morse)
            fall_level = nra.get("fall_risk_level")
            if fall_level:
                # Clinosim Morse risk bands ("low"/"moderate"/"high") → HL7 v3
                # ObservationInterpretation L / N / H.
                _fall_interp: dict[str, tuple[str, str, str]] = {
                    "low": ("L", "Low", "低リスク"),
                    "moderate": ("N", "Normal", "中リスク"),
                    "high": ("H", "High", "高リスク"),
                }
                code_val, display_en, display_ja = _fall_interp.get(
                    str(fall_level).lower(), ("N", "Normal", "通常")
                )
                interp_display = display_ja if ctx.country == "JP" else display_en
                interp_text = (
                    f"転倒リスク: {fall_level}"
                    if ctx.country == "JP"
                    else f"Fall risk: {fall_level}"
                )
                obs["interpretation"] = [{
                    "coding": [{
                        "system": get_system_uri("hl7-observation-interpretation"),
                        "code": code_val,
                        "display": interp_display,
                    }],
                    "text": interp_text,
                }]
            out.append(obs)

    # --- ADL assessments: Barthel index ---
    for i, adl in enumerate(ctx.record.get("adl_assessments") or []):
        adl_date = adl.get("date")
        effective = adl_date if isinstance(adl_date, str) else (
            str(adl_date) if adl_date is not None else None
        )

        barthel = adl.get("barthel_score")
        if barthel is not None:
            obs = _obs_base(f"barthel-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("96761-2", lang)],
                "text": code_lookup("loinc", "96761-2", lang) or "Total score Barthel Index",
            }
            obs["valueInteger"] = int(barthel)
            out.append(obs)

    # --- Intake and output records ---
    for i, io in enumerate(ctx.record.get("intake_output_records") or []):
        io_date = io.get("date")
        effective = io_date if isinstance(io_date, str) else (
            str(io_date) if io_date is not None else None
        )

        # Fluid intake total 24h = iv + oral + other (LOINC 9108-2)
        iv_ml = io.get("intake_iv_ml") or 0
        oral_ml = io.get("intake_oral_ml") or 0
        other_in_ml = io.get("intake_other_ml") or 0
        intake_total = iv_ml + oral_ml + other_in_ml
        if intake_total > 0:
            obs = _obs_base(f"intake-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("9108-2", lang)],
                "text": code_lookup("loinc", "9108-2", lang) or "Fluid intake total 24 hour",
            }
            obs["valueQuantity"] = {
                "value": int(intake_total),
                "unit": "mL",
                "system": get_system_uri("ucum"),
                "code": "mL",
            }
            out.append(obs)

        # Urine output 24h (component; LOINC 9192-6)
        urine_ml = io.get("output_urine_ml")
        if urine_ml is not None:
            obs = _obs_base(f"urine-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("9192-6", lang)],
                "text": code_lookup("loinc", "9192-6", lang) or "Urine output 24 hour",
            }
            obs["valueQuantity"] = {
                "value": int(urine_ml),
                "unit": "mL",
                "system": get_system_uri("ucum"),
                "code": "mL",
            }
            out.append(obs)

        # Fluid output total 24h = urine + drain + other (aggregate; LOINC 9262-7)
        drain_ml = io.get("output_drain_ml") or 0
        other_out_ml = io.get("output_other_ml") or 0
        output_total = (urine_ml or 0) + drain_ml + other_out_ml
        if output_total > 0:
            obs = _obs_base(f"output-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("9262-7", lang)],
                "text": code_lookup("loinc", "9262-7", lang) or "Fluid output total 24 hour",
            }
            obs["valueQuantity"] = {
                "value": int(output_total),
                "unit": "mL",
                "system": get_system_uri("ucum"),
                "code": "mL",
            }
            out.append(obs)

    return out


def _build_immunizations(ctx: BundleContext) -> list[dict]:
    """Build FHIR Immunization resources from CIF immunizations (CVX codes, AD-30/AD-56).

    Each ImmunizationRecord in ctx.record["immunizations"] maps to one FHIR Immunization.
    Display text is resolved via lookup("cvx", code, lang); never emitted as display == code.
    US output contains no Japanese characters; JP output uses Japanese display when available.
    """
    lang = "ja" if ctx.country == "JP" else "en"
    out: list[dict] = []

    for i, imm in enumerate(ctx.record.get("immunizations") or []):
        if isinstance(imm, dict):
            cvx = imm.get("vaccine_cvx", "")
            occurrence = imm.get("occurrence_date", "")
            status = imm.get("status", "completed")
            primary_source = imm.get("primary_source", True)
        else:
            # ImmunizationRecord dataclass (in-memory path)
            cvx = getattr(imm, "vaccine_cvx", "")
            occurrence = getattr(imm, "occurrence_date", "")
            status = getattr(imm, "status", "completed")
            primary_source = getattr(imm, "primary_source", True)

        if not cvx:
            continue

        display = code_lookup("cvx", cvx, lang)
        coding: dict[str, Any] = {"system": get_system_uri("cvx"), "code": cvx}
        if display and display != cvx:
            coding["display"] = display

        vaccine_code: dict[str, Any] = {"coding": [coding]}
        if display and display != cvx:
            vaccine_code["text"] = display

        # occurrence_date may be a date object or ISO string; normalise to YYYY-MM-DD
        occ_str = occurrence.isoformat() if hasattr(occurrence, "isoformat") else str(occurrence)

        resource: dict[str, Any] = {
            "resourceType": "Immunization",
            "id": f"imm-{ctx.patient_id}-{i}",
            "status": status,
            "vaccineCode": vaccine_code,
            "patient": {"reference": f"Patient/{ctx.patient_id}"},
            "occurrenceDateTime": occ_str,
            "primarySource": primary_source,
        }
        out.append(resource)

    return out


def _build_lab_observation(
    order: dict, result: dict, patient_id: str, index: int,
    country: str, patient_sex: str = "", encounter_id: str = "",
) -> dict | None:
    """Build FHIR Observation resource for a lab result."""
    value = result.get("value")
    if value is None:
        return None

    # Prefer the result's canonical analyte name (stat/serial/alias resolved upstream)
    # over the raw order label, so the code mapping resolves (AD-55).
    lab_name = result.get("lab_name") or order.get("display_name", "Unknown")

    # test_name → code mapping still lives in locale (internal name → standard code)
    country_code = "JP" if country != "US" else "US"
    lang = "ja" if country_code == "JP" else "en"
    code_map = load_code_mapping("lab", country_code)
    code_value = code_map.get(lab_name, order.get("order_code", ""))

    # Display text comes from codes module (via standard code)
    code_system_key = "jlac10" if country_code == "JP" else "loinc"
    display_name = code_lookup(code_system_key, code_value, lang) if code_value else lab_name
    if display_name == code_value:  # no translation found
        display_name = lab_name
    code_system = get_system_uri(code_system_key)

    # Use encounter_id-scoped IDs to avoid collisions across patient's multiple encounters
    enc_scope = encounter_id or patient_id
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"lab-{enc_scope}-{index:04d}",
        "status": "final",
        "category": [{
            "coding": [{
                "system": get_system_uri("hl7-observation-category"),
                "code": "laboratory",
                "display": _localize_display("Laboratory", country, _CATEGORY_DISPLAY_JA),
            }],
            "text": _localize_display("Laboratory", country, _CATEGORY_DISPLAY_JA),
        }],
        "code": {
            "coding": [{"system": code_system, "code": code_value, "display": display_name}],
            "text": display_name,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": result.get("result_datetime", ""),
    }

    if isinstance(value, (int, float)):
        unit_str = result.get("unit", "")
        resource["valueQuantity"] = {
            "value": value,
            "unit": unit_str,
            "system": get_system_uri("ucum"),
            "code": unit_str,  # UCUM code identical to display unit
        }
    else:
        resource["valueString"] = str(value)

    # Reference range (JP: JCCLS共用基準範囲)
    ref_range = _build_reference_range(lab_name, patient_sex, country_code)
    if ref_range:
        resource["referenceRange"] = ref_range

    # Interpretation — recompute from value vs reference range when possible
    # (ensures consistency per FHIR spec: both must be consistent when provided).
    # Fall back to flag-based mapping for non-numeric or no-range cases.
    flag = result.get("flag")
    interp_map = {
        "H": {"code": "H", "display": "High"},
        "L": {"code": "L", "display": "Low"},
        "H*": {"code": "HH", "display": "Critical high"},
        "L*": {"code": "LL", "display": "Critical low"},
        "critical": {"code": "AA", "display": "Critical abnormal"},
    }
    coded: dict[str, str] | None = None
    if isinstance(value, (int, float)) and ref_range:
        # Find normal range (type=normal or unlabeled first entry)
        normal_rng = None
        for rng in ref_range:
            tc = (rng.get("type") or {}).get("coding", [{}])[0].get("code", "")
            if tc == "normal" or not tc:
                normal_rng = rng
                break
        if normal_rng:
            low_v = (normal_rng.get("low") or {}).get("value")
            high_v = (normal_rng.get("high") or {}).get("value")
            is_critical = flag in ("H*", "L*", "critical")
            out_low = low_v is not None and value < low_v
            out_high = high_v is not None and value > high_v
            if is_critical and out_low:
                coded = {"code": "LL", "display": "Critical low"}
            elif is_critical and out_high:
                coded = {"code": "HH", "display": "Critical high"}
            elif is_critical:
                coded = {"code": "AA", "display": "Critical abnormal"}
            elif out_low:
                coded = {"code": "L", "display": "Low"}
            elif out_high:
                coded = {"code": "H", "display": "High"}
            else:
                coded = {"code": "N", "display": "Normal"}
    if coded is None:
        coded = interp_map.get(flag) if flag else {"code": "N", "display": "Normal"}
    coded = _localize_interp(coded, country)
    resource["interpretation"] = [{
        "coding": [{
            "system": get_system_uri("hl7-observation-interpretation"),
            **coded,
        }],
    }]

    # Encounter reference (use order's encounter_id, fallback to primary)
    enc_ref = order.get("encounter_id", "") or encounter_id
    if enc_ref:
        resource["encounter"] = {"reference": f"Encounter/{enc_ref}"}

    # Performer (lab technician or ordering physician)
    performer_id = result.get("performed_by", "") or order.get("ordered_by", "")
    if performer_id:
        resource["performer"] = [{"reference": f"Practitioner/{performer_id}"}]

    return resource


def _build_vital_observations(
    vs: dict, patient_id: str, index: int, country: str = "US",
    encounter_id: str = "",
) -> list[dict]:
    """Build FHIR Observation resources for vital signs (one per parameter)."""
    entries = []

    # (field, loinc, display_en, display_ja, unit, low, high, critical_low, critical_high, time_offset_sec)
    # crit_high=None means no upper critical bound (e.g., SpO2 cannot be critically high)
    # time_offset: per-field realistic delay within a vital-sign set
    # BP/HR measured simultaneously (same device cycle), Temp added later, RR counted last
    _vital_map = [
        ("heart_rate", "8867-4", "Heart rate", "脈拍", "/min", 60, 100, 40, 130, 0),
        ("systolic_bp", "8480-6", "Systolic blood pressure", "収縮期血圧", "mm[Hg]", 90, 140, 80, 200, 0),
        ("diastolic_bp", "8462-4", "Diastolic blood pressure", "拡張期血圧", "mm[Hg]", 60, 90, 50, 120, 0),
        ("spo2", "2708-6", "Oxygen saturation", "酸素飽和度", "%", 95, 100, 88, None, 5),
        ("temperature_celsius", "8310-5", "Body temperature", "体温", "Cel", 36.0, 37.5, 35.0, 39.5, 30),
        ("respiratory_rate", "9279-1", "Respiratory rate", "呼吸数", "/min", 12, 20, 8, 30, 60),
    ]

    for field, loinc, display_en, display_ja, unit, low, high, crit_low, crit_high, offset_sec in _vital_map:
        display = display_ja if country == "JP" else display_en
        value = vs.get(field)
        if value is None:
            continue

        obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": f"vs-{encounter_id or patient_id}-{index:04d}-{field}",
            "status": "final",
            "category": [{
                "coding": [{
                    "system": get_system_uri("hl7-observation-category"),
                    "code": "vital-signs",
                    "display": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                }],
                "text": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
            }],
            "code": {
                "coding": [{"system": get_system_uri("loinc"), "code": loinc, "display": display}],
                "text": display,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "valueQuantity": {
                "value": value,
                "unit": unit,
                "system": get_system_uri("ucum"),
                "code": unit,
            },
        }
        # Add timestamp with per-field offset (BP/HR same, Temp +30s, RR +60s, SpO2 +5s)
        timestamp = vs.get("timestamp")
        if timestamp:
            try:
                from datetime import datetime as _dt
                from datetime import timedelta as _td
                base_dt = _dt.fromisoformat(str(timestamp).replace("Z","+00:00").split("+")[0])
                shifted = base_dt + _td(seconds=offset_sec)
                obs["effectiveDateTime"] = shifted.isoformat()
            except (ValueError, TypeError):
                obs["effectiveDateTime"] = timestamp if isinstance(timestamp, str) else str(timestamp)

        # Encounter reference
        if encounter_id:
            obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}

        # Performer (nurse who measured)
        performer_id = vs.get("measured_by", "")
        if performer_id:
            obs["performer"] = [{"reference": f"Practitioner/{performer_id}"}]

        # Reference range — normal range (always) + critical range (when defined)
        range_text = "成人正常範囲" if country == "JP" else "Normal adult range"
        crit_text = "パニック値" if country == "JP" else "Critical range"
        ref_ranges = [{
            "low": {"value": low, "unit": unit, "system": get_system_uri("ucum"), "code": unit},
            "high": {"value": high, "unit": unit, "system": get_system_uri("ucum"), "code": unit},
            "type": {
                "coding": [{
                    "system": get_system_uri("hl7-referencerange-meaning"),
                    "code": "normal",
                    "display": "正常範囲" if country == "JP" else "Normal Range",
                }],
            },
            "text": range_text,
        }]
        # Add critical range as separate entry (panic values)
        if crit_low is not None or crit_high is not None:
            crit_range: dict[str, Any] = {
                "type": {
                    "coding": [{
                        "system": get_system_uri("hl7-referencerange-meaning"),
                        "code": "treatment",
                        "display": "パニック範囲" if country == "JP" else "Critical Range",
                    }],
                },
                "text": crit_text,
            }
            if crit_low is not None:
                crit_range["low"] = {"value": crit_low, "unit": unit, "system": get_system_uri("ucum"), "code": unit}
            if crit_high is not None:
                crit_range["high"] = {"value": crit_high, "unit": unit, "system": get_system_uri("ucum"), "code": unit}
            ref_ranges.append(crit_range)
        obs["referenceRange"] = ref_ranges

        # Interpretation (compute from value vs reference range — always consistent)
        interp_code = "N"
        interp_display = "Normal"
        if crit_low is not None and value <= crit_low:
            interp_code = "LL"; interp_display = "Critical low"
        elif crit_high is not None and value >= crit_high:
            interp_code = "HH"; interp_display = "Critical high"
        elif value < low:
            interp_code = "L"; interp_display = "Low"
        elif value > high:
            interp_code = "H"; interp_display = "High"
        obs["interpretation"] = [{
            "coding": [{
                "system": get_system_uri("hl7-observation-interpretation"),
                "code": interp_code,
                "display": _localize_display(interp_display, country, _INTERPRETATION_DISPLAY_JA),
            }],
        }]

        entries.append(_entry(obs))

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
        loc_label_ja = {"A": "意識清明", "V": "呼びかけに反応", "P": "痛み刺激に反応", "U": "無反応"}
        display = loc_label_ja.get(loc, loc_display) if country == "JP" else loc_display
        loc_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": f"vs-{encounter_id or patient_id}-{index:04d}-loc",
            "status": "final",
            "category": [{
                "coding": [{
                    "system": get_system_uri("hl7-observation-category"),
                    "code": "vital-signs",
                    "display": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                }],
                "text": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
            }],
            "code": {
                "coding": [{
                    "system": get_system_uri("loinc"),
                    "code": "80288-4",
                    "display": "Level of consciousness AVPU",
                }],
                "text": "意識レベル (AVPU)" if country == "JP" else "Level of consciousness (AVPU)",
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "valueCodeableConcept": {
                "coding": [{
                    "system": get_system_uri("snomed-ct"),
                    "code": loc_snomed,
                    "display": loc_display,
                }],
                "text": display,
            },
        }
        timestamp = vs.get("timestamp")
        if timestamp:
            loc_obs["effectiveDateTime"] = timestamp if isinstance(timestamp, str) else str(timestamp)
        if encounter_id:
            loc_obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}
        entries.append(_entry(loc_obs))

    # Supplemental oxygen (LOINC 3151-8 = inhaled oxygen flow rate)
    if vs.get("on_supplemental_oxygen"):
        flow = vs.get("oxygen_flow_rate_lpm")
        device = vs.get("oxygen_delivery_device", "")
        o2_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": f"vs-{encounter_id or patient_id}-{index:04d}-o2",
            "status": "final",
            "category": [{
                "coding": [{
                    "system": get_system_uri("hl7-observation-category"),
                    "code": "vital-signs",
                    "display": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                }],
                "text": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
            }],
            "code": {
                "coding": [{
                    "system": get_system_uri("loinc"),
                    "code": "3151-8",
                    "display": "Inhaled oxygen flow rate",
                }],
                "text": "酸素投与量" if country == "JP" else "Supplemental oxygen flow rate",
            },
            "subject": {"reference": f"Patient/{patient_id}"},
        }
        if flow is not None:
            o2_obs["valueQuantity"] = {
                "value": flow,
                "unit": "L/min",
                "system": get_system_uri("ucum"),
                "code": "L/min",
            }
        if device:
            o2_obs["component"] = [{
                "code": {
                    "coding": [{
                        "system": get_system_uri("loinc"),
                        "code": "8478-0",
                        "display": "Inhaled oxygen delivery system",
                    }],
                },
                "valueString": device,
            }]
        timestamp = vs.get("timestamp")
        if timestamp:
            o2_obs["effectiveDateTime"] = timestamp if isinstance(timestamp, str) else str(timestamp)
        if encounter_id:
            o2_obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}
        entries.append(_entry(o2_obs))

    return entries
