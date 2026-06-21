"""FHIR R4 Encounter resource builder (FA-1 Phase 5).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: depends only on
:mod:`clinosim.codes`, the leaf reference/localization dicts, and the shared
fragment helpers in :mod:`_fhir_common` — never importing back through the
adapter facade.
"""

from __future__ import annotations

import uuid
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules.output._fhir_common import _make_participant, _map_encounter_status
from clinosim.modules.output._fhir_localization import (
    _CLASS_DISPLAY_JA,
    _dept_display,
    _localize_display,
)
from clinosim.modules.output._fhir_reference_data import (
    _ENCOUNTER_TYPE_SNOMED,
    _ENCOUNTER_TYPE_SNOMED_JA,
)


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
        "status": _map_encounter_status(enc.get("status", "")),
        "class": {
            "system": get_system_uri("hl7-v3-actcode"),
            "code": class_code,
            "display": _localize_display(class_display, country, _CLASS_DISPLAY_JA),
        },
        "subject": {"reference": f"Patient/{patient_id}"},
    }

    # Type (SNOMED)
    type_info = _ENCOUNTER_TYPE_SNOMED.get(enc_type)
    if type_info:
        coding = {"system": get_system_uri("snomed-ct"), **type_info}
        if country == "JP" and enc_type in _ENCOUNTER_TYPE_SNOMED_JA:
            coding["display"] = _ENCOUNTER_TYPE_SNOMED_JA[enc_type]
        resource["type"] = [{"coding": [coding]}]

    # Priority (Encounter.priority)
    priority = enc.get("priority", "")
    if priority:
        priority_display = {"EM": "emergency", "UR": "urgent", "R": "routine"}.get(priority, "")
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
            # Length in minutes
            try:
                from datetime import datetime as _dt
                start = _dt.fromisoformat(str(enc["admission_datetime"]).replace("Z","+00:00").split("+")[0])
                end = _dt.fromisoformat(str(enc["discharge_datetime"]).replace("Z","+00:00").split("+")[0])
                minutes = int((end - start).total_seconds() / 60)
                resource["length"] = {
                    "value": minutes,
                    "unit": "min",
                    "system": get_system_uri("ucum"),
                    "code": "min",
                }
            except (ValueError, TypeError):
                pass

    if enc.get("chief_complaint"):
        # reasonCode: use diagnosis display in target language (codes module)
        # Falls back to English chief_complaint text if no code available
        lang = "ja" if country == "JP" else "en"
        if admit_dx_code:
            reason_text = code_lookup(admit_dx_system, admit_dx_code, lang)
            if reason_text == admit_dx_code:
                reason_text = enc["chief_complaint"]  # fallback to English text
        else:
            reason_text = enc["chief_complaint"]
        resource["reasonCode"] = [{"text": reason_text}]
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
        participants.append(_make_participant("ATND", "attender", attending))
    if admitter and admitter != attending:
        participants.append(_make_participant("ADM", "admitter", admitter))
    if discharger and discharger != attending and discharger != admitter:
        participants.append(_make_participant("DIS", "discharger", discharger))
    elif attending and not admitter:
        # If only attending exists, they also serve as admitter/discharger
        participants.append(_make_participant("ADM", "admitter", attending))
        if enc.get("discharge_datetime"):
            participants.append(_make_participant("DIS", "discharger", attending))

    if participants:
        resource["participant"] = participants

    # Diagnosis reference (link to Condition)
    if primary_dx_code:
        resource["diagnosis"] = [{
            "condition": {"reference": f"Condition/cond-{encounter_id}-primary"},
            "use": {
                "coding": [{
                    "system": get_system_uri("hl7-diagnosis-role"),
                    "code": "DD",
                    "display": "Discharge diagnosis",
                }],
            },
            "rank": 1,
        }]

    # Hospitalization (admit source / discharge disposition / re-admission)
    hosp: dict[str, Any] = {}
    if enc.get("admit_source"):
        hosp["admitSource"] = {
            "coding": [{
                "system": get_system_uri("hl7-admit-source"),
                "code": enc["admit_source"],
            }],
        }
    if enc.get("discharge_disposition"):
        hosp["dischargeDisposition"] = {
            "coding": [{
                "system": get_system_uri("hl7-discharge-disposition"),
                "code": enc["discharge_disposition"],
            }],
        }
    # Re-admission flag (FHIR standard: hospitalization.reAdmission CodeableConcept)
    # Using HL7 v2 table 0092 "Re-admission Indicator" — the canonical source.
    if is_readmission:
        hosp["reAdmission"] = {
            "coding": [{
                "system": get_system_uri("hl7-v2-0092"),
                "code": "R",
                "display": "Re-admission",
            }],
            "text": "再入院" if country == "JP" else "Re-admission",
        }
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
                "display": f"{bed_number}号室" if country == "JP" else f"Bed {bed_number}",
            },
            "status": "completed" if enc.get("discharge_datetime") else "active",
        })
    # Secondary: Ward Location
    if ward_id:
        locations.append({
            "location": {
                "reference": f"Location/loc-ward-{ward_id}",
                "display": f"{ward_id}病棟" if country == "JP" else f"Ward {ward_id}",
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
