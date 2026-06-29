"""FHIR R4 lab + vital-sign Observation builders (FA-1 Phase 13).

Canonical numeric Observation resources: per-order lab values (via
_build_lab_observation helper) and per-encounter vital signs. Microbiology,
nursing flowsheets, and Immunization were split out in PR3 into
_fhir_microbiology.py / _fhir_nursing.py / _fhir_immunization.py
respectively. The ctx-taking builder imports the shared BundleContext
from _fhir_common, so this module never imports back through the adapter
(no cycle).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping
from clinosim.modules._shared import get_attr_or_key
from clinosim.modules.output._fhir_common import BundleContext, _build_reference_range, _entry
from clinosim.modules.output._fhir_diagnostic_report import lab_obs_id
from clinosim.modules.output._fhir_localization import (
    _CATEGORY_DISPLAY_JA,
    _INTERPRETATION_DISPLAY_JA,
    _localize_display,
    _localize_interp,
)
from clinosim.modules.output._fhir_service_request import build_panel_counter, order_to_sr_id
from clinosim.types.encounter import Order, OrderType


def _o(order: Any, name: str, default: Any = None) -> Any:
    """Dual-access helper: dataclass attribute OR dict key (production path)."""
    return get_attr_or_key(order, name, default)


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

    # encounter_id must be non-empty: the production path always provides ctx.primary_enc_id,
    # and the diagnostic-report reader (parse_lab_obs_id) matches on the same encounter_id.
    # A patient_id fallback would silently break basedOn linkage (PR-90 silent-no-op class).
    assert encounter_id, (
        "_build_lab_observation: encounter_id must be non-empty. "
        "All call sites pass ctx.primary_enc_id which is validated before the loop."
    )
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": lab_obs_id(encounter_id, index),
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
    lab_order_objects = [
        o for o in orders
        if _o(o, "order_type") in (OrderType.LAB, "lab")
    ]
    panel_counter = build_panel_counter(lab_order_objects)

    out: list[dict[str, Any]] = []
    for i, order in enumerate(orders):
        if isinstance(order, Order):
            # Order dataclass path (tests + future direct-object pipeline).
            if order.order_type != OrderType.LAB or order.result is None:
                continue
            # Convert to dict for _build_lab_observation (which uses dict.get access).
            order_dict = dataclasses.asdict(order)
            result_dict: dict[str, Any] = order_dict.get("result") or {}
            sr_id: str | None = order_to_sr_id(order, panel_counter)
        elif isinstance(order, dict):
            # JSON-deserialized dict path (production CIF loaded from json.load).
            if order.get("order_type") not in ("lab", OrderType.LAB):
                continue
            result_data = order.get("result")
            if not result_data:
                continue
            order_dict = order
            result_dict = result_data if isinstance(result_data, dict) else {}
            # Now computable for dicts via dict-compatible panel_counter (Fix 1+2).
            sr_id = order_to_sr_id(order, panel_counter)
        else:
            continue

        obs = _build_lab_observation(
            order_dict, result_dict, ctx.patient_id, i,
            ctx.country, ctx.patient_sex, ctx.primary_enc_id,
        )
        if obs:
            if sr_id is not None:
                obs["basedOn"] = [{"reference": f"ServiceRequest/{sr_id}"}]
            out.append(obs)
    return out
