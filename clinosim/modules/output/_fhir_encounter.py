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


def _build_encounter(
    enc: dict, patient_id: str,
    is_readmission: bool = False, prior_encounter_id: str | None = None,
    primary_dx_code: str = "",
    country: str = "US",
    admit_dx_code: str = "",
    admit_dx_system: str = "icd-10-cm",
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
        **({"meta": {"profile": [
            "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Encounter"
        ]}} if str(country).upper() == "JP" else {}),
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
        elif _cc.startswith("Follow-up") or _cc.startswith("フォローアップ") or \
             _cc.startswith("Post-discharge"):
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
        resource["type"] = [{"coding": [
            _coding_with_display("snomed-ct", type_code, resolve_lang(country))
        ]}]

    # Priority (Encounter.priority)
    priority = enc.get("priority", "")
    if priority:
        priority_display = {"EM": "emergency", "UR": "urgent", "R": "routine"}.get(priority, "")
        # C5-03 (session 43 cycle 5): localize priority display for JP output.
        from clinosim.modules.output._fhir_localization import (
            _ACT_PRIORITY_DISPLAY_JA,
        )
        priority_display = _localize_display(
            priority_display, country, _ACT_PRIORITY_DISPLAY_JA
        )
        resource["priority"] = {
            "coding": [{
                "system": get_system_uri("hl7-v3-actpriority"),
                "code": priority,
                "display": priority_display,
            }],
        }

    # Service type (department)
    department = enc.get("department_id", "") or "internal_medicine"
    dept_display = _dept_display(department, country)
    resource["serviceType"] = {
        "coding": [{
            "system": get_system_uri("hl7-service-type"),
            "code": department,
            "display": dept_display,
        }],
        "text": dept_display,
    }

    if enc.get("admission_datetime"):
        resource["period"] = {"start": enc["admission_datetime"]}
        if enc.get("discharge_datetime"):
            resource["period"]["end"] = enc["discharge_datetime"]
            # Length — C5-11 (session 43 cycle 5): use days for LOS ≥ 1 day
            # (typical IMP encounters run to 20+ days = large minute counts;
            # UCUM `d` is more natural for chart LOS displays).
            try:
                from datetime import datetime as _dt
                start = _dt.fromisoformat(str(enc["admission_datetime"]).replace("Z","+00:00").split("+")[0])
                end = _dt.fromisoformat(str(enc["discharge_datetime"]).replace("Z","+00:00").split("+")[0])
                total_min = int((end - start).total_seconds() / 60)
                if total_min >= 1440:  # 1 day
                    days = round(total_min / 1440, 2)
                    resource["length"] = {
                        "value": days,
                        "unit": "d",
                        "system": get_system_uri("ucum"),
                        "code": "d",
                    }
                else:
                    resource["length"] = {
                        "value": total_min,
                        "unit": "min",
                        "system": get_system_uri("ucum"),
                        "code": "min",
                    }
            except (ValueError, TypeError):
                pass

    if enc.get("chief_complaint"):
        # reasonCode: use diagnosis display in target language (codes module)
        # Falls back to English chief_complaint text if no code available
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
        if _reason_code:
            reason_text = code_lookup(_reason_system, _reason_code, lang)
            if reason_text == _reason_code:
                reason_text = enc["chief_complaint"]  # fallback to English text
        else:
            reason_text = enc["chief_complaint"]
        # C2-29 (session 42 cycle 2): also emit reasonCode.coding pointing at
        # the admission diagnosis code (ICD-10 or ICD-10-CM), not just text.
        # This gives every Encounter a machine-processable reason.
        rc: dict[str, Any] = {"text": reason_text}
        if _reason_code:
            rc["coding"] = [_coding_with_display(_reason_system, _reason_code, lang)]
        resource["reasonCode"] = [rc]
        # reasonReference: link to primary Condition (if dx exists)
        if primary_dx_code:
            resource["reasonReference"] = [{
                "reference": f"Condition/cond-{encounter_id}-primary",
            }]

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
    _discharger_effective = discharger or (
        attending if _is_ip and enc.get("discharge_datetime") else ""
    )
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
        _dd_display = _localize_display(
            "Discharge diagnosis", country, _DIAGNOSIS_ROLE_DISPLAY_JA
        )
        resource["diagnosis"] = [{
            "condition": {"reference": f"Condition/cond-{encounter_id}-primary"},
            "use": {
                "coding": [{
                    "system": get_system_uri("hl7-diagnosis-role"),
                    "code": "DD",
                    "display": _dd_display,
                }],
            },
            "rank": 1,
        }]

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
            "coding": [{
                "system": get_system_uri("hl7-v2-0092"),
                "code": "R",
                "display": "Re-admission",
            }],
            "text": "再入院" if is_jp(country) else "Re-admission",
        }
    # C2-18 (session 42 cycle 2): IMP encounters must carry a hospitalization
    # block. When both admit_source and discharge_disposition are missing
    # (edge case: 8 encounters in the JP p=10k cohort), fall back to sane
    # defaults — admit_source=hosp (from hospital administration, catch-all)
    # and discharge_disposition=home when the encounter is finished.
    if _emit_hospitalization and not hosp.get("admitSource"):
        _default_code = "hosp"
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
    if (_emit_hospitalization and not hosp.get("dischargeDisposition")
            and _is_finished):
        _dd_code = "home"
        _dd_disp = code_lookup("hl7-discharge-disposition", _dd_code, _lang)
        _dd_coding = {
            "system": get_system_uri("hl7-discharge-disposition"),
            "code": _dd_code,
        }
        if _dd_disp and _dd_disp != _dd_code:
            _dd_coding["display"] = _dd_disp
        hosp["dischargeDisposition"] = {"coding": [_dd_coding]}
    if hosp:
        resource["hospitalization"] = hosp

    # Service provider (department Organization in _facility.json)
    if department:
        resource["serviceProvider"] = {
            "reference": f"Organization/dept-{department.replace('_', '-')}",
        }

    # Location (bed → ward hierarchy via partOf in facility bundle)
    ward_id = enc.get("ward_id", "")
    bed_number = enc.get("bed_number", "")
    locations: list[dict[str, Any]] = []
    # Primary: Bed Location (most specific), if we have a bed assignment
    if bed_number and "-" in bed_number and ward_id not in ("ER", "OPD"):
        locations.append({
            "location": {
                "reference": f"Location/loc-bed-{bed_number}",
                "display": f"{bed_number}号室" if is_jp(country) else f"Bed {bed_number}",
            },
            "status": "completed" if enc.get("discharge_datetime") else "active",
        })
    # Secondary: Ward Location
    if ward_id:
        locations.append({
            "location": {
                "reference": f"Location/loc-ward-{ward_id}",
                "display": f"{ward_id}病棟" if is_jp(country) else f"Ward {ward_id}",
            },
            "status": "completed" if enc.get("discharge_datetime") else "active",
        })
    # CO-5 (session 42 cycle 3): fallback Encounter.location for AMB/EMER.
    # If ward_id is empty (typical for outpatient / ED), attach the
    # department Organization as a location surrogate. Not a physical bed but
    # gives Encounter.location non-empty per JP EHR practice.
    if not locations and department:
        loc_ref = f"loc-dept-{department.replace('_', '-')}"
        loc_display = dept_display or department
        locations.append({
            "location": {
                "reference": f"Location/{loc_ref}",
                "display": loc_display,
            },
            "status": "completed" if enc.get("discharge_datetime") else "active",
        })
    if locations:
        resource["location"] = locations

    # Readmission: link to prior encounter
    if is_readmission and prior_encounter_id:
        resource["partOf"] = {"reference": f"Encounter/{prior_encounter_id}"}
        # Add READM type to existing types
        if "type" in resource:
            resource["type"].append({
                "coding": [{
                    "system": get_system_uri("hl7-v3-actcode"),
                    "code": "READM",
                    "display": "Readmission",
                }],
            })
        else:
            resource["type"] = [{
                "coding": [{
                    "system": get_system_uri("hl7-v3-actcode"),
                    "code": "READM",
                    "display": "Readmission",
                }],
            }]

    return resource
