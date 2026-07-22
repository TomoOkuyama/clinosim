"""FHIR R4 Encounter resource builder (FA-1 Phase 5).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: depends only on
:mod:`clinosim.codes`, the leaf reference/localization dicts, and the shared
fragment helpers in :mod:`_fhir_common` — never importing back through the
adapter facade.
"""

from __future__ import annotations

import uuid
from typing import Any

from clinosim.codes import get_system_uri, system_key_for
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output._fhir_common import (
    _coding_with_display,
    _make_participant,
    _map_diagnosis_code,
    _map_encounter_status,
)
from clinosim.modules.output._fhir_localization import (
    _CLASS_DISPLAY_JA,
    _dept_display,
    _localize_display,
)
from clinosim.modules.output._fhir_reference_data import _ENCOUNTER_TYPE_SNOMED_CODE


def _compute_encounter_length(start_iso: str, end_iso: str) -> dict[str, Any] | None:
    """Compute FHIR ``Encounter.length`` from ISO-8601 period bounds.

    Returns ``None`` if either bound cannot be parsed or if the interval
    is non-positive. Emits UCUM ``d`` (days) for LOS ≥ 1 day, else ``min``.

    Session 45: extracted from ``_build_encounter`` so the ED-encounter
    synthesis path in ``fhir_r4_adapter._bb_encounters`` can share the same
    computation instead of only IMP paths getting length.
    """
    if not start_iso or not end_iso:
        return None
    try:
        from datetime import datetime as _dt

        start = _dt.fromisoformat(str(start_iso).replace("Z", "+00:00").split("+")[0])
        end = _dt.fromisoformat(str(end_iso).replace("Z", "+00:00").split("+")[0])
    except (ValueError, TypeError):
        return None
    total_min = int((end - start).total_seconds() / 60)
    if total_min <= 0:
        return None
    if total_min >= 1440:  # 1 day
        return {
            "value": round(total_min / 1440, 2),
            "unit": "d",
            "system": get_system_uri("ucum"),
            "code": "d",
        }
    return {
        "value": total_min,
        "unit": "min",
        "system": get_system_uri("ucum"),
        "code": "min",
    }


def _build_encounter(
    enc: dict,
    patient_id: str,
    is_readmission: bool = False,
    prior_encounter_id: str | None = None,
    primary_dx_code: str = "",
    country: str = "US",
    admit_dx_code: str = "",
    admit_dx_system: str = "icd-10-cm",
    icu_transferred_day: int = -1,
    deceased: bool = False,
    chronic_condition_codes: list[str] | None = None,
    record_orders: list | None = None,  # CY8-03: DIET Order source for dietPreference
) -> dict:
    """Build FHIR Encounter resource."""
    encounter_id = enc.get("encounter_id", str(uuid.uuid4()))
    enc_type = enc.get("encounter_type", "")

    # Map class
    if enc_type == "inpatient":
        class_code, class_display = "IMP", "inpatient encounter"
    elif enc_type == "emergency":
        class_code, class_display = "EMER", "emergency"
    else:
        class_code, class_display = "AMB", "ambulatory"

    resource: dict[str, Any] = {
        "resourceType": "Encounter",
        "id": encounter_id,
        # C2-20 (session 42 cycle 2): JP Core Encounter profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Encounter"]}}
            if str(country).upper() == "JP"
            else {}
        ),
        "status": _map_encounter_status(enc.get("status", "")),
        "class": {
            "system": get_system_uri("hl7-v3-actcode"),
            "code": class_code,
            "display": _localize_display(class_display, country, _CLASS_DISPLAY_JA),
        },
        "subject": {"reference": f"Patient/{patient_id}"},
    }

    # Type (SNOMED). C1-05 (session 41 cycle 1): outpatient AMB no longer
    # uniformly "Patient-initiated encounter". Use existing context to pick a
    # more specific SNOMED code — JP EHR reality: 再診 (follow-up check-up) is
    # the vast majority of outpatient visits, 初診 (first-visit consultation)
    # is a small minority, and screening/immunization visits keep the generic
    # patient-initiated code.
    type_code = _ENCOUNTER_TYPE_SNOMED_CODE.get(enc_type)
    if enc_type == "outpatient":
        _cc = str(enc.get("chief_complaint", "") or "")
        # Health screening / annual check / immunization → keep the generic
        # patient-initiated code (270427003) — not a disease-specific visit.
        if any(kw in _cc for kw in ("健康診断", "screening", "予防接種", "vaccination")):
            type_code = "270427003"
        elif _cc.startswith("Follow-up") or _cc.startswith("フォローアップ") or _cc.startswith("Post-discharge"):
            type_code = "185349003"  # Encounter for check-up
        elif primary_dx_code:
            # Default for chronic-condition outpatient visits: check-up
            # (follow-up). Consultation (11429006) reserved for the rare
            # first-visit path — detected via encounter YAML flags in a
            # future cycle (needs new CIF field).
            type_code = "185349003"
    if type_code:
        # C2-01 (session 42): use _coding_with_display so codes lacking a
        # codes/data entry emit without display=code fallback (FHIR interop).
        resource["type"] = [{"coding": [_coding_with_display("snomed-ct", type_code, resolve_lang(country))]}]

    # Priority (Encounter.priority)
    priority = enc.get("priority", "")
    # CY7-06 (Chain-7): default priority "R" (routine) when unset. Real EHR
    # systems always carry a priority — an empty priority is a data-model
    # completeness gap. 8 IMP encounters in cycle 7 baseline had priority
    # empty (all `type == 32485007` general hospital admission).
    if not priority:
        priority = "R"
    if priority:
        priority_display = {"EM": "emergency", "UR": "urgent", "R": "routine"}.get(priority, "")
        # C5-03 (session 43 cycle 5): localize priority display for JP output.
        from clinosim.modules.output._fhir_localization import (
            _ACT_PRIORITY_DISPLAY_JA,
        )

        priority_display = _localize_display(priority_display, country, _ACT_PRIORITY_DISPLAY_JA)
        resource["priority"] = {
            "coding": [
                {
                    "system": get_system_uri("hl7-v3-actpriority"),
                    "code": priority,
                    "display": priority_display,
                }
            ],
        }

    # Service type (department)
    # feedback FB-F7: hl7-service-type CodeSystem は診療科 code の canonical
    # source ではない(numeric code 系のみ)。department 名(internal_medicine /
    # health_checkup 等)を直接 code として使うと validator が "code 未定義" と
    # reject する。JP-authoritative 診療科 CodeSystem が確立するまで text-only
    # CodeableConcept で emit(Coverage.type と同じ no-fabrication policy)。
    department = enc.get("department_id", "") or "internal_medicine"
    dept_display = _dept_display(department, country)
    resource["serviceType"] = {"text": dept_display}

    if enc.get("admission_datetime"):
        resource["period"] = {"start": enc["admission_datetime"]}
        if enc.get("discharge_datetime"):
            resource["period"]["end"] = enc["discharge_datetime"]
            # Length — C5-11 (session 43 cycle 5): use days for LOS ≥ 1 day
            # (typical IMP encounters run to 20+ days = large minute counts;
            # UCUM `d` is more natural for chart LOS displays).
            length = _compute_encounter_length(enc["admission_datetime"], enc["discharge_datetime"])
            if length is not None:
                resource["length"] = length

    # C5-22 (session 43): Encounter.classHistory + statusHistory for
    # inpatient encounters that transitioned through ward → ICU (icu_transferred_day
    # captured in inpatient.py simulator loop) OR whose planned → in-progress
    # → finished status transitions matter for audit trail.
    if class_code == "IMP" and enc.get("admission_datetime"):
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        try:
            _adm = _dt.fromisoformat(str(enc["admission_datetime"]).replace("Z", "+00:00").split("+")[0])
        except (ValueError, TypeError):
            _adm = None
        _dis = None
        if enc.get("discharge_datetime"):
            try:
                _dis = _dt.fromisoformat(str(enc["discharge_datetime"]).replace("Z", "+00:00").split("+")[0])
            except (ValueError, TypeError):
                pass
        # classHistory: ward IMP → ICU IMP transition
        if icu_transferred_day is not None and icu_transferred_day >= 0 and _adm:
            _icu_transfer_dt = _adm + _td(days=icu_transferred_day)
            _act_uri = get_system_uri("hl7-v3-actcode")
            class_history: list[dict[str, Any]] = [
                {
                    "class": {
                        "system": _act_uri,
                        "code": "IMP",
                        "display": _localize_display(
                            "inpatient ward",
                            country,
                            _CLASS_DISPLAY_JA,
                        ),
                    },
                    "period": {
                        "start": enc["admission_datetime"],
                        "end": _icu_transfer_dt.isoformat(),
                    },
                },
                {
                    "class": {
                        "system": _act_uri,
                        "code": "ACUTE",  # HL7 ActCode Acute inpatient
                        "display": _localize_display(
                            "ICU",
                            country,
                            _CLASS_DISPLAY_JA,
                        ),
                    },
                    "period": {
                        "start": _icu_transfer_dt.isoformat(),
                        **({"end": enc["discharge_datetime"]} if enc.get("discharge_datetime") else {}),
                    },
                },
            ]
            resource["classHistory"] = class_history
        # statusHistory: planned → in-progress → finished (deterministic
        # timeline: planned = admission-1h, in-progress = admission,
        # finished = discharge). Only emit when we have both timestamps.
        if _adm:
            _planned_start = (_adm - _td(hours=1)).isoformat()
            status_history: list[dict[str, Any]] = [
                {
                    "status": "planned",
                    "period": {
                        "start": _planned_start,
                        "end": enc["admission_datetime"],
                    },
                },
            ]
            _cur_status = _map_encounter_status(enc.get("status", ""))
            if _cur_status == "finished" and _dis:
                status_history.append(
                    {
                        "status": "in-progress",
                        "period": {
                            "start": enc["admission_datetime"],
                            "end": enc["discharge_datetime"],
                        },
                    }
                )
                status_history.append(
                    {
                        "status": "finished",
                        "period": {"start": enc["discharge_datetime"]},
                    }
                )
            else:
                status_history.append(
                    {
                        "status": "in-progress",
                        "period": {"start": enc["admission_datetime"]},
                    }
                )
            resource["statusHistory"] = status_history

    if enc.get("chief_complaint"):
        # reasonCode: use diagnosis display in target language (codes module)
        # Falls back to JP-stashed chief_complaint_ja on JP output, or
        # English chief_complaint text otherwise, if no code available.
        lang = resolve_lang(country)
        # C4-24 (session 43 cycle 4): route the admission dx system + code
        # through the country's diagnosis code system so JP output never
        # emits icd-10-cm under an icd-10 semantic surface (was 4 encounters
        # in baseline where CIF stored icd-10-cm CM-granular codes as-is).
        # `system_key_for("diagnosis", ...)` yields `icd-10-cm` for US and
        # `icd-10` for JP; `_map_diagnosis_code` folds CM-granular to WHO
        # roots via code_mapping_diagnosis.
        _reason_system = system_key_for("diagnosis", country)
        _reason_code = _map_diagnosis_code(admit_dx_code, country) if admit_dx_code else ""
        # Issue #360 G1 (iris4h-ai 2026-07-22): the fallback path (used when
        # admit_dx_code is empty or code_lookup returns the raw code) must
        # prefer the JP chief_complaint stashed by the simulator on JP
        # output — CIF stores English canonical (AD-30), so the plain
        # ``enc["chief_complaint"]`` is English and would reach the JP
        # Clinical Cockpit as English protocol text (feedback G1).
        _chief_en = enc.get("chief_complaint", "")
        _chief_ja = enc.get("chief_complaint_ja", "") or ""
        _fallback_text = _chief_ja if lang == "ja" and _chief_ja else _chief_en
        if _reason_code:
            reason_text = code_lookup(_reason_system, _reason_code, lang)
            if reason_text == _reason_code:
                reason_text = _fallback_text
        else:
            reason_text = _fallback_text
        # C2-29 (session 42 cycle 2): also emit reasonCode.coding pointing at
        # the admission diagnosis code (ICD-10 or ICD-10-CM), not just text.
        # This gives every Encounter a machine-processable reason.
        rc: dict[str, Any] = {"text": reason_text}
        if _reason_code:
            rc["coding"] = [_coding_with_display(_reason_system, _reason_code, lang)]
        resource["reasonCode"] = [rc]
        # reasonReference: link to primary Condition (if dx exists)
        if primary_dx_code:
            resource["reasonReference"] = [
                {
                    "reference": f"Condition/cond-{encounter_id}-primary",
                }
            ]

    # Participant: attending, admitter, discharger
    participants: list[dict[str, Any]] = []
    attending = enc.get("attending_physician_id", "")
    admitter = enc.get("admitting_physician_id", "")
    discharger = enc.get("discharging_physician_id", "")

    if attending:
        participants.append(_make_participant("ATND", "attender", attending, country))
    # C4-30 (session 43 cycle 4): emit ADM / DIS for IMP encounters even
    # when the practitioner is the same as attending — FHIR R4 allows the
    # same Practitioner across multiple participant.type entries, and JP
    # Core Encounter recommends admitter / discharger tracking for inpatient
    # workflows. Previously only 4 IMP encounters emitted ADM/DIS because
    # attending == admitter suppressed the elif fallback.
    _is_ip = class_code in ("IMP", "EMER")
    _admitter_effective = admitter or (attending if _is_ip else "")
    _discharger_effective = discharger or (attending if _is_ip and enc.get("discharge_datetime") else "")
    if _admitter_effective:
        participants.append(_make_participant("ADM", "admitter", _admitter_effective, country))
    if _discharger_effective:
        participants.append(_make_participant("DIS", "discharger", _discharger_effective, country))

    if participants:
        resource["participant"] = participants

    # Diagnosis reference (link to Condition)
    if primary_dx_code:
        # C5-04 (session 43 cycle 5): localize diagnosis role display.
        from clinosim.modules.output._fhir_localization import (
            _DIAGNOSIS_ROLE_DISPLAY_JA,
        )

        _dd_display = _localize_display("Discharge diagnosis", country, _DIAGNOSIS_ROLE_DISPLAY_JA)
        diagnosis_list: list[dict[str, Any]] = [
            {
                "condition": {"reference": f"Condition/cond-{encounter_id}-primary"},
                "use": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-diagnosis-role"),
                            "code": "DD",
                            "display": _dd_display,
                        }
                    ],
                },
                "rank": 1,
            }
        ]
        # C5-12 (session 43 history-chain continuation): add secondary
        # diagnoses for polymorbid encounters. Chronic conditions carried
        # by the patient at encounter time contribute Encounter.diagnosis[]
        # with `use=CM` (Comorbidity, from HL7 diagnosis-role valueset) and
        # rank 2..N. References the patient-scoped chronic Condition ids
        # emitted by _fhir_conditions (`cond-chronic-{patient}-{i:02d}`).
        # De-dupe when the chronic base matches the primary dx (already
        # emitted as rank=1).
        if chronic_condition_codes:
            _cm_display = _localize_display(
                "Comorbidity diagnosis",
                country,
                _DIAGNOSIS_ROLE_DISPLAY_JA,
            )
            _primary_base = primary_dx_code.split(".")[0] if primary_dx_code else ""
            _rank = 2
            for _i, _ccode in enumerate(chronic_condition_codes):
                if not _ccode:
                    continue
                if _ccode.split(".")[0] == _primary_base:
                    continue  # already emitted as primary rank=1
                diagnosis_list.append(
                    {
                        "condition": {
                            "reference": f"Condition/cond-chronic-{patient_id}-{_i:02d}",
                        },
                        "use": {
                            "coding": [
                                {
                                    "system": get_system_uri("hl7-diagnosis-role"),
                                    "code": "CM",
                                    "display": _cm_display,
                                }
                            ],
                        },
                        "rank": _rank,
                    }
                )
                _rank += 1
        resource["diagnosis"] = diagnosis_list

    # Hospitalization (admit source / discharge disposition / re-admission).
    # C1-02/C1-03 (session 41 cycle 1): resolve display via authoritative
    # hl7-admit-source / hl7-discharge-disposition code data.
    # C1-01 (session 41 cycle 1): FHIR R4 Encounter.hospitalization models
    # inpatient/emergency admission context (admission/discharge, re-admission
    # flag, etc.); skip for AMB (ambulatory) so we don't emit outp→home rings
    # on every 30-minute outpatient visit.
    hosp: dict[str, Any] = {}
    _emit_hospitalization = class_code != "AMB"
    _lang = resolve_lang(country)
    if _emit_hospitalization and enc.get("admit_source"):
        _admit_code = enc["admit_source"]
        _admit_disp = code_lookup("hl7-admit-source", _admit_code, _lang)
        _admit_coding: dict[str, Any] = {
            "system": get_system_uri("hl7-admit-source"),
            "code": _admit_code,
        }
        if _admit_disp and _admit_disp != _admit_code:
            _admit_coding["display"] = _admit_disp
        hosp["admitSource"] = {"coding": [_admit_coding]}
    if _emit_hospitalization and enc.get("discharge_disposition"):
        _dd_code = enc["discharge_disposition"]
        _dd_disp = code_lookup("hl7-discharge-disposition", _dd_code, _lang)
        _dd_coding: dict[str, Any] = {
            "system": get_system_uri("hl7-discharge-disposition"),
            "code": _dd_code,
        }
        if _dd_disp and _dd_disp != _dd_code:
            _dd_coding["display"] = _dd_disp
        hosp["dischargeDisposition"] = {"coding": [_dd_coding]}
    # Re-admission flag (FHIR standard: hospitalization.reAdmission CodeableConcept)
    # Using HL7 v2 table 0092 "Re-admission Indicator" — the canonical source.
    if _emit_hospitalization and is_readmission:
        hosp["reAdmission"] = {
            "coding": [
                {
                    "system": get_system_uri("hl7-v2-0092"),
                    "code": "R",
                    "display": "Re-admission",
                }
            ],
            "text": "再入院" if is_jp(country) else "Re-admission",
        }
    # C2-18 (session 42 cycle 2): IMP encounters must carry a hospitalization
    # block. When both admit_source and discharge_disposition are missing
    # (edge case: 8 encounters in the JP p=10k cohort), fall back to sane
    # defaults — admit_source=other (unspecified catch-all; authoritative HL7
    # admit-source CS r4 7.2.0 concepts: hosp-trans/emd/outp/born/gp/mp/
    # nursing/psych/rehab/other) and discharge_disposition=home when finished.
    # Issue #332 (session 62): 従来 "hosp" は authoritative CS 未収録で
    # v9 rest 2 件 unknown-code error 発火 → "other" へ訂正
    # (`hosp-trans` は他院転入で specific meaning、不明時 emit は誤情報)。
    if _emit_hospitalization and not hosp.get("admitSource"):
        _default_code = "other"
        _default_disp = code_lookup("hl7-admit-source", _default_code, _lang)
        _default_coding: dict[str, Any] = {
            "system": get_system_uri("hl7-admit-source"),
            "code": _default_code,
        }
        if _default_disp and _default_disp != _default_code:
            _default_coding["display"] = _default_disp
        hosp["admitSource"] = {"coding": [_default_coding]}
    # C4-20 (session 43 cycle 4): CIF encounter status is "completed"
    # (mapped to FHIR "finished" by _map_encounter_status). Prior comparison
    # to raw "finished" never matched, so 4 IMP encounters retained no
    # dischargeDisposition. Use both CIF and FHIR values so future refactors
    # (e.g. status stored in FHIR form) still trigger the fallback.
    _cif_status = enc.get("status", "")
    _is_finished = _cif_status in ("completed", "finished")
    if _emit_hospitalization and not hosp.get("dischargeDisposition") and _is_finished:
        _dd_code = "home"
        _dd_disp = code_lookup("hl7-discharge-disposition", _dd_code, _lang)
        _dd_coding = {
            "system": get_system_uri("hl7-discharge-disposition"),
            "code": _dd_code,
        }
        if _dd_disp and _dd_disp != _dd_code:
            _dd_coding["display"] = _dd_disp
        hosp["dischargeDisposition"] = {"coding": [_dd_coding]}
    # CY8-03 fix (session 48 cycle 8):Encounter.hospitalization.dietPreference
    # を CIF の DIET Order から derive。IMP/EMER encounter で diet order あれば
    # 一意の diet 種別を text-only CodeableConcept として emit。
    # (SNOMED diet codes は正典未確定、no-fabrication policy per text-only)
    if _emit_hospitalization:
        _rord = record_orders or []
        diet_orders = [
            o
            for o in _rord
            if str(o.get("order_type") if isinstance(o, dict) else getattr(o, "order_type", ""))
            in ("diet", "OrderType.DIET")
            and (o.get("encounter_id") if isinstance(o, dict) else getattr(o, "encounter_id", "")) == encounter_id
        ]
        if diet_orders:
            _diet_labels = {
                "NPO": "絶食" if is_jp(country) else "NPO (nothing by mouth)",
                "clear_liquid": "流動食" if is_jp(country) else "Clear liquids",
                "soft_diet": "軟菜食" if is_jp(country) else "Soft diet",
                "regular_diet": "常食" if is_jp(country) else "Regular diet",
                "diabetic_diet": "糖尿病食" if is_jp(country) else "Diabetic diet",
                "low_sodium": "減塩食" if is_jp(country) else "Low-sodium diet",
                "renal_diet": "腎臓食" if is_jp(country) else "Renal diet",
            }
            seen = []
            for o in diet_orders:
                name = str(o.get("display_name") if isinstance(o, dict) else getattr(o, "display_name", ""))
                label = _diet_labels.get(name, name)
                if label and label not in seen:
                    seen.append(label)
            if seen:
                hosp["dietPreference"] = [{"text": lb} for lb in seen]

    if hosp:
        resource["hospitalization"] = hosp

    # Service provider (department Organization in _facility.json)
    # CY8-04 fix (session 48 cycle 8):department 未設定 encounter は
    # hospital-main を fallback として serviceProvider に emit。従来 79.6% →
    # 100% 化。department 名の "_" は "-" に normalize(既存 pattern)。
    if department:
        resource["serviceProvider"] = {
            "reference": f"Organization/dept-{department.replace('_', '-')}",
        }
    else:
        resource["serviceProvider"] = {
            "reference": "Organization/hospital-main",
        }

    # Location (bed → ward hierarchy via partOf in facility bundle)
    ward_id = enc.get("ward_id", "")
    bed_number = enc.get("bed_number", "")
    locations: list[dict[str, Any]] = []
    # Primary: Bed Location (most specific), if we have a bed assignment
    if bed_number and "-" in bed_number and ward_id not in ("ER", "OPD"):
        locations.append(
            {
                "location": {
                    "reference": f"Location/loc-bed-{bed_number}",
                    "display": f"{bed_number}号室" if is_jp(country) else f"Bed {bed_number}",
                },
                "status": "completed" if enc.get("discharge_datetime") else "active",
            }
        )
    # Secondary: Ward Location
    if ward_id:
        locations.append(
            {
                "location": {
                    "reference": f"Location/loc-ward-{ward_id}",
                    "display": f"{ward_id}病棟" if is_jp(country) else f"Ward {ward_id}",
                },
                "status": "completed" if enc.get("discharge_datetime") else "active",
            }
        )
    # CO-5 (session 42 cycle 3): fallback Encounter.location for AMB/EMER.
    # If ward_id is empty (typical for outpatient / ED), attach the
    # department Organization as a location surrogate. Not a physical bed but
    # gives Encounter.location non-empty per JP EHR practice.
    if not locations and department:
        loc_ref = f"loc-dept-{department.replace('_', '-')}"
        loc_display = dept_display or department
        locations.append(
            {
                "location": {
                    "reference": f"Location/{loc_ref}",
                    "display": loc_display,
                },
                "status": "completed" if enc.get("discharge_datetime") else "active",
            }
        )
    if locations:
        resource["location"] = locations

    # Readmission: link to prior encounter via partOf.
    # session 59 #299:従来 `Encounter.type[]` に v3-ActCode "READM" を
    # 追加していたが、READM は v3-ActCode に存在しない code(v5 で 24 件
    # error)。FHIR 正式には `Encounter.hospitalization.reAdmission`
    # (v2-0092 "R" = Re-admission)で表現、上の line 435-444 で既に emit
    # 済み。type[] への重複追加は無効な CS binding を生むので撤廃。
    if is_readmission and prior_encounter_id:
        resource["partOf"] = {"reference": f"Encounter/{prior_encounter_id}"}

    return resource
