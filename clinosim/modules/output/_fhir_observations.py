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

from clinosim.codes import get_system_uri, system_key_for
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping
from clinosim.modules._shared import get_attr_or_key, is_jp, is_us, resolve_lang, sanitize_id_token
from clinosim.modules.output._fhir_common import (
    BundleContext,
    _build_reference_range,
    _entry,
    to_fhir_datetime,
)
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
    order: dict,
    result: dict,
    patient_id: str,
    index: int,
    country: str,
    patient_sex: str = "",
    encounter_id: str = "",
) -> dict | None:
    """Build FHIR Observation resource for a lab result."""
    value = result.get("value")
    if value is None:
        return None

    # Prefer the result's canonical analyte name (stat/serial/alias resolved upstream)
    # over the raw order label, so the code mapping resolves (AD-55).
    lab_name = result.get("lab_name") or order.get("display_name", "Unknown")

    # test_name → code mapping still lives in locale (internal name → standard code)
    country_code = "US" if is_us(country) else "JP"
    lang = resolve_lang(country_code)
    code_map = load_code_mapping("lab", country_code)
    if lab_name in code_map:
        code_value = code_map[lab_name]
        code_system_key = system_key_for("lab", country_code)
    else:
        # Unmapped lab_name falls back to the raw order_code (LOINC-shaped) — the
        # system must fall back with it, since tagging a LOINC code under the
        # country's mapped system (e.g. jlac10) would produce an incoherent coding
        # (same fix as _bb_microbiology's culture-code resolution, TODO.md 2026-07-04).
        code_value = order.get("order_code", "")
        code_system_key = "loinc"

    # Display text comes from codes module (via standard code)
    # #321 session 61:code_lookup が None を返す場合(該当 code に翻訳が
    # ない、v6.1 で 190 件 code.text 欠落 error 発火)、display_name が
    # None のまま emit されて JP_Observation_LabResult の code.text min=1
    # を満たさない。empty / None / code-echo 全てを lab_name にフォール
    # バックさせる。
    display_name = code_lookup(code_system_key, code_value, lang) if code_value else None
    if not display_name or display_name == code_value:
        display_name = lab_name
    code_system = get_system_uri(code_system_key)

    # encounter_id must be non-empty: the production path always provides ctx.primary_enc_id,
    # and the diagnostic-report reader (parse_lab_obs_id) matches on the same encounter_id.
    # A patient_id fallback would silently break basedOn linkage (PR-90 silent-no-op class).
    assert encounter_id, (
        "_build_lab_observation: encounter_id must be non-empty. "
        "All call sites pass ctx.primary_enc_id which is validated before the loop."
    )
    # feedback FB-F6: 特定 LOINC は対応標準 profile を要求。
    # LOINC 39156-5 (BMI) → hl7.org/.../bmi、8480-6/8462-4 (BP) → .../bp。
    # JP コホートも JP Core LabResult + 該当 vital profile を stacking 可能。
    _extra_profiles: list[str] = []
    _lab_code = str(result.get("lab_name") or code_value or "")
    if _lab_code == "39156-5":
        _extra_profiles.append("http://hl7.org/fhir/StructureDefinition/bmi")
    # BP 個別 obs は bp profile が component 構造を要求するため、
    # 別 Observation で発行される limitation あり(TODO: 将来 combined 85354-9)。
    # ここでは profile 付与を保留、TODO として cycle 9 に持越し。

    _profiles: list[str] = []
    if is_jp(country):
        _profiles.append("http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult")
    _profiles.extend(_extra_profiles)

    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": lab_obs_id(encounter_id, index),
        # Session 46 chain #2: JP Core Observation_LabResult profile.
        # feedback FB-F6: 該当 LOINC の standard profile も stack 追加。
        **({"meta": {"profile": _profiles}} if _profiles else {}),
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": get_system_uri("hl7-observation-category"),
                        "code": "laboratory",
                        "display": _localize_display("Laboratory", country, _CATEGORY_DISPLAY_JA),
                    }
                ],
                "text": _localize_display("Laboratory", country, _CATEGORY_DISPLAY_JA),
            }
        ],
        "code": {
            "coding": [{"system": code_system, "code": code_value, "display": display_name}],
            "text": display_name,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": result.get("result_datetime", ""),
    }
    # Session 45 seed=400 verification: JP Core Observation_Common profile
    # recommends dual coding (JLAC10 primary + LOINC interop) so downstream
    # consumers not conversant with JLAC10 can still recognize the analyte.
    # Condition / Procedure already dual-code (JP Core + WHO); Observation
    # was the outlier. Attach the LOINC equivalent when the analyte has one.
    if country_code == "JP":
        us_code_map = load_code_mapping("lab", "US")
        loinc_code = us_code_map.get(lab_name)
        if loinc_code and loinc_code != code_value:
            loinc_display = code_lookup("loinc", loinc_code, "en") or lab_name
            resource["code"]["coding"].append(
                {
                    "system": get_system_uri("loinc"),
                    "code": loinc_code,
                    "display": loinc_display,
                }
            )

    if isinstance(value, (int, float)):
        unit_str = result.get("unit", "")
        # #323 session 61:FHIR R4 ele-1 は空文字列 field を禁止。unit が
        # 未設定時(unit_str == "")は unit / code / system 全て omit
        # (v6.1 で 44 件 error 発火)。value のみ emit する。
        _vq: dict[str, Any] = {"value": value}
        if unit_str:
            _vq["unit"] = unit_str
            _vq["system"] = get_system_uri("ucum")
            _vq["code"] = unit_str  # UCUM code identical to display unit
        resource["valueQuantity"] = _vq
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
    if coded is None:
        coded = {"code": "N", "display": "Normal"}
    coded = _localize_interp(coded, country)
    resource["interpretation"] = [
        {
            "coding": [
                {
                    "system": get_system_uri("hl7-observation-interpretation"),
                    **coded,
                }
            ],
        }
    ]

    # Encounter reference (use order's encounter_id, fallback to primary)
    enc_ref = order.get("encounter_id", "") or encounter_id
    if enc_ref:
        resource["encounter"] = {"reference": f"Encounter/{enc_ref}"}

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
    # analyte). Mirrors session-42 Coverage.type text-only precedent.
    _method_text = "自動分析器測定" if is_jp(country) else "Automated laboratory measurement"
    resource["method"] = {"text": _method_text}

    return resource


def _build_bp_component(
    loinc: str,
    display_en: str,
    display_ja: str,
    value: float,
    normal_low: float,
    normal_high: float,
    crit_low: float,
    crit_high: float,
    country: str,
) -> dict[str, Any]:
    """Build one `component[]` entry inside the BP-panel Observation (#210).

    Encodes the LOINC code (systolic 8480-6 / diastolic 8462-4),
    valueQuantity in mmHg, the paired referenceRange (normal + critical),
    and the derived interpretation flag. Reference-range and
    interpretation ranges match the pre-#210 per-Observation shape so
    downstream flag semantics stay identical.
    """
    display = display_ja if is_jp(country) else display_en
    unit = "mm[Hg]"
    interp_code = "N"
    interp_display = "Normal"
    if value <= crit_low:
        interp_code, interp_display = "LL", "Critical low"
    elif value >= crit_high:
        interp_code, interp_display = "HH", "Critical high"
    elif value < normal_low:
        interp_code, interp_display = "L", "Low"
    elif value > normal_high:
        interp_code, interp_display = "H", "High"

    normal_text = "成人正常範囲" if is_jp(country) else "Normal adult range"
    crit_text = "パニック値" if is_jp(country) else "Critical range"
    return {
        "code": {
            "coding": [{"system": get_system_uri("loinc"), "code": loinc, "display": display}],
            "text": display,
        },
        "valueQuantity": {
            "value": value,
            "unit": unit,
            "system": get_system_uri("ucum"),
            "code": unit,
        },
        "referenceRange": [
            {
                "low": {"value": normal_low, "unit": unit, "system": get_system_uri("ucum"), "code": unit},
                "high": {"value": normal_high, "unit": unit, "system": get_system_uri("ucum"), "code": unit},
                "type": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-referencerange-meaning"),
                            "code": "normal",
                            "display": "正常範囲" if is_jp(country) else "Normal Range",
                        }
                    ],
                },
                "text": normal_text,
            },
            {
                "low": {"value": crit_low, "unit": unit, "system": get_system_uri("ucum"), "code": unit},
                "high": {"value": crit_high, "unit": unit, "system": get_system_uri("ucum"), "code": unit},
                "type": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-referencerange-meaning"),
                            "code": "treatment",
                            "display": "パニック範囲" if is_jp(country) else "Critical Range",
                        }
                    ],
                },
                "text": crit_text,
            },
        ],
        "interpretation": [
            {
                "coding": [
                    {
                        "system": get_system_uri("hl7-observation-interpretation"),
                        "code": interp_code,
                        "display": _localize_display(interp_display, country, _INTERPRETATION_DISPLAY_JA),
                    }
                ],
            }
        ],
    }


def _build_vital_observations(
    vs: dict,
    patient_id: str,
    index: int,
    country: str = "US",
    encounter_id: str = "",
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

    # (field, loinc, display_en, display_ja, unit, low, high, critical_low, critical_high, time_offset_sec)
    # crit_high=None means no upper critical bound (e.g., SpO2 cannot be critically high)
    # time_offset: per-field realistic delay within a vital-sign set
    # BP/HR measured simultaneously (same device cycle), Temp added later, RR counted last
    #
    # NOTE: `systolic_bp` / `diastolic_bp` used to appear here as separate
    # Observations; they are now consolidated into a single BP panel
    # Observation emitted at the end of this function (see #210). Reference
    # ranges for the components live in the panel's per-component
    # `referenceRange[]` block, matching the FHIR base "bp" profile shape.
    _vital_map = [
        ("heart_rate", "8867-4", "Heart rate", "脈拍", "/min", 60, 100, 40, 130, 0),
        ("spo2", "2708-6", "Oxygen saturation", "酸素飽和度", "%", 95, 100, 88, None, 5),
        ("temperature_celsius", "8310-5", "Body temperature", "体温", "Cel", 36.0, 37.5, 35.0, 39.5, 30),
        ("respiratory_rate", "9279-1", "Respiratory rate", "呼吸数", "/min", 12, 20, 8, 30, 60),
    ]

    for field, loinc, display_en, display_ja, unit, low, high, crit_low, crit_high, offset_sec in _vital_map:
        display = display_ja if is_jp(country) else display_en
        value = vs.get(field)
        if value is None:
            continue

        obs: dict[str, Any] = {
            "resourceType": "Observation",
            # Session 52 fix (iris4h-ai HAPI): vital field names carry
            # underscores (systolic_bp / oxygen_saturation etc.); FHIR R4
            # id type forbids '_'. sanitize_id_token routes the fragment
            # through a single normalization point.
            "id": f"vs-{encounter_id or patient_id}-{index:04d}-{sanitize_id_token(field)}",
            # Session 46 chain #2: JP Core Observation_Common profile for vitals.
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"]}}
                if is_jp(country)
                else {}
            ),
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-observation-category"),
                            "code": "vital-signs",
                            "display": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                        }
                    ],
                    "text": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                }
            ],
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

                base_dt = _dt.fromisoformat(str(timestamp).replace("Z", "+00:00").split("+")[0])
                shifted = base_dt + _td(seconds=offset_sec)
                obs["effectiveDateTime"] = shifted.isoformat()
            except (ValueError, TypeError):
                obs["effectiveDateTime"] = to_fhir_datetime(timestamp)

        # Encounter reference
        if encounter_id:
            obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}

        # Performer (nurse who measured)
        performer_id = vs.get("measured_by", "")
        if performer_id:
            obs["performer"] = [{"reference": f"Practitioner/{performer_id}"}]

        # Reference range — normal range (always) + critical range (when defined)
        range_text = "成人正常範囲" if is_jp(country) else "Normal adult range"
        crit_text = "パニック値" if is_jp(country) else "Critical range"
        ref_ranges = [
            {
                "low": {"value": low, "unit": unit, "system": get_system_uri("ucum"), "code": unit},
                "high": {"value": high, "unit": unit, "system": get_system_uri("ucum"), "code": unit},
                "type": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-referencerange-meaning"),
                            "code": "normal",
                            "display": "正常範囲" if is_jp(country) else "Normal Range",
                        }
                    ],
                },
                "text": range_text,
            }
        ]
        # Add critical range as separate entry (panic values)
        if crit_low is not None or crit_high is not None:
            crit_range: dict[str, Any] = {
                "type": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-referencerange-meaning"),
                            "code": "treatment",
                            "display": "パニック範囲" if is_jp(country) else "Critical Range",
                        }
                    ],
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
            interp_code, interp_display = "LL", "Critical low"
        elif crit_high is not None and value >= crit_high:
            interp_code, interp_display = "HH", "Critical high"
        elif value < low:
            interp_code, interp_display = "L", "Low"
        elif value > high:
            interp_code, interp_display = "H", "High"
        obs["interpretation"] = [
            {
                "coding": [
                    {
                        "system": get_system_uri("hl7-observation-interpretation"),
                        "code": interp_code,
                        "display": _localize_display(interp_display, country, _INTERPRETATION_DISPLAY_JA),
                    }
                ],
            }
        ]

        entries.append(_entry(obs))

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
        bp_display = "血圧" if is_jp(country) else "Blood pressure panel"
        bp_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": f"vs-{encounter_id or patient_id}-{index:04d}-bp-panel",
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"]}}
                if is_jp(country)
                else {}
            ),
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-observation-category"),
                            "code": "vital-signs",
                            "display": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                        }
                    ],
                    "text": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                }
            ],
            "code": {
                "coding": [{"system": get_system_uri("loinc"), "code": "85354-9", "display": bp_display}],
                "text": bp_display,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "component": [
                _build_bp_component(
                    loinc="8480-6",
                    display_en="Systolic blood pressure",
                    display_ja="収縮期血圧",
                    value=sbp,
                    normal_low=90,
                    normal_high=140,
                    crit_low=80,
                    crit_high=200,
                    country=country,
                ),
                _build_bp_component(
                    loinc="8462-4",
                    display_en="Diastolic blood pressure",
                    display_ja="拡張期血圧",
                    value=dbp,
                    normal_low=60,
                    normal_high=90,
                    crit_low=50,
                    crit_high=120,
                    country=country,
                ),
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
            bp_obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}
        performer_id = vs.get("measured_by", "")
        if performer_id:
            bp_obs["performer"] = [{"reference": f"Practitioner/{performer_id}"}]
        entries.append(_entry(bp_obs))

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
        display = loc_label_ja.get(loc, loc_display) if is_jp(country) else loc_display
        loc_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": f"vs-{encounter_id or patient_id}-{index:04d}-loc",
            # Session 46 chain #2: JP Core Observation_Common profile for vitals.
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"]}}
                if is_jp(country)
                else {}
            ),
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-observation-category"),
                            "code": "vital-signs",
                            "display": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                        }
                    ],
                    "text": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": get_system_uri("loinc"),
                        "code": "80288-4",
                        # Issue #384 hotfix follow-up (session 66): the AVPU
                        # Observation.code emit was hardcoded, so PR #385's
                        # loinc.yaml + override_allowlist update did NOT
                        # propagate to the FHIR output — v28 confirmed 1,252
                        # errors persisted with the SHORTNAME emit
                        # "Level of consciousness AVPU". Adopt the
                        # fhirserver-side canonical directly
                        # (LONG_COMMON_NAME with "score" suffix, matching
                        # loinc.yaml's en for this code). Refactoring the
                        # hardcode to a code_lookup call is a separate
                        # cleanup; the immediate fix is the string.
                        "display": "Level of consciousness AVPU score",
                    }
                ],
                "text": "意識レベル (AVPU)" if is_jp(country) else "Level of consciousness (AVPU)",
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "valueCodeableConcept": {
                "coding": [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": loc_snomed,
                        "display": display,
                    }
                ],
                "text": display,
            },
        }
        timestamp = vs.get("timestamp")
        if timestamp:
            loc_obs["effectiveDateTime"] = to_fhir_datetime(timestamp)
        if encounter_id:
            loc_obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}
        # RM-1 (session 42): forward performer (nurse measured_by) on LOC obs.
        _perf = vs.get("measured_by", "")
        if _perf:
            loc_obs["performer"] = [{"reference": f"Practitioner/{_perf}"}]
        entries.append(_entry(loc_obs))

    # Supplemental oxygen (LOINC 3151-8 = inhaled oxygen flow rate)
    if vs.get("on_supplemental_oxygen"):
        flow = vs.get("oxygen_flow_rate_lpm")
        device = vs.get("oxygen_delivery_device", "")
        o2_obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": f"vs-{encounter_id or patient_id}-{index:04d}-o2",
            # Session 46 chain #2: JP Core Observation_Common profile for vitals.
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"]}}
                if is_jp(country)
                else {}
            ),
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-observation-category"),
                            "code": "vital-signs",
                            "display": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                        }
                    ],
                    "text": _localize_display("Vital Signs", country, _CATEGORY_DISPLAY_JA),
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": get_system_uri("loinc"),
                        "code": "3151-8",
                        "display": "Inhaled oxygen flow rate",
                    }
                ],
                "text": "酸素投与量" if is_jp(country) else "Supplemental oxygen flow rate",
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
                    "valueString": device,
                }
            ]
        timestamp = vs.get("timestamp")
        if timestamp:
            o2_obs["effectiveDateTime"] = to_fhir_datetime(timestamp)
        if encounter_id:
            o2_obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}
        # RM-1 (session 42): forward performer on O2 obs.
        _perf = vs.get("measured_by", "")
        if _perf:
            o2_obs["performer"] = [{"reference": f"Practitioner/{_perf}"}]
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
    lab_order_objects = [o for o in orders if _o(o, "order_type") in (OrderType.LAB, "lab")]
    panel_counter = build_panel_counter(lab_order_objects)

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
        )
        if obs:
            if sr_id is not None:
                obs["basedOn"] = [{"reference": f"ServiceRequest/{sr_id}"}]
            out.append(obs)
    return out
