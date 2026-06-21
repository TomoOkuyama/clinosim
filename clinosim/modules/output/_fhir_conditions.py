"""FHIR R4 Condition resource builder (FA-1 conditions).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.modules.output._fhir_common import (
    _build_diagnosis_codeable_concept,
    _infer_severity,
    _map_diagnosis_code,
    _severity_coding,
)
from clinosim.modules.output._fhir_localization import (
    _CATEGORY_DISPLAY_JA,
    _localize_display,
)


def _build_conditions(record: dict, patient_id: str, country: str) -> list[dict]:
    """Build FHIR Condition resources from diagnosis and chronic conditions.

    Generates:
    - Primary encounter diagnosis (from clinical_diagnosis) with severity
    - Chronic conditions (from patient.chronic_conditions) with onset dates
    Deduplicates by ICD base code.
    """
    conditions: list[dict] = []
    seen_codes: set[str] = set()

    dx = record.get("clinical_diagnosis", {})
    encounters = record.get("encounters", [])
    encounter_id = encounters[0].get("encounter_id", "") if encounters else ""
    encounter_type = encounters[0].get("encounter_type", "") if encounters else ""
    is_inpatient = encounter_type == "inpatient"
    admission_dt = encounters[0].get("admission_datetime", "") if encounters else ""
    discharge_dt = encounters[0].get("discharge_datetime", "") if encounters else ""
    deceased = record.get("deceased", False)

    country_code = "JP" if country != "US" else "US"
    lang = "ja" if country_code == "JP" else "en"
    icd_system_key = "icd-10" if country_code == "JP" else "icd-10-cm"

    # --- Primary diagnosis (encounter diagnosis) ---
    dx_code = dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", "")
    if dx_code:
        base_code = dx_code.split(".")[0]
        seen_codes.add(base_code)

        # Determine severity from physiological states
        severity = _infer_severity(record)

        # clinicalStatus: resolved if discharged alive, active if deceased (didn't resolve)
        if is_inpatient:
            clinical_status = "active" if deceased or not discharge_dt else "resolved"
        else:
            clinical_status = "resolved"

        cond: dict[str, Any] = {
            "resourceType": "Condition",
            "id": f"cond-{encounter_id}-primary" if encounter_id else f"cond-{patient_id}-primary",
            "clinicalStatus": {
                "coding": [{
                    "system": get_system_uri("hl7-condition-clinical"),
                    "code": clinical_status,
                }],
            },
            "verificationStatus": {
                "coding": [{
                    "system": get_system_uri("hl7-condition-ver-status"),
                    "code": "confirmed",
                }],
            },
            "category": [{
                "coding": [{
                    "system": get_system_uri("hl7-condition-category"),
                    "code": "encounter-diagnosis",
                    "display": _localize_display("Encounter Diagnosis", country, _CATEGORY_DISPLAY_JA),
                }],
            }],
            "code": _build_diagnosis_codeable_concept(
                _map_diagnosis_code(dx_code, country), icd_system_key, country
            ),
            "subject": {"reference": f"Patient/{patient_id}"},
        }

        if severity:
            cond["severity"] = _severity_coding(severity, country)

        if admission_dt:
            cond["onsetDateTime"] = admission_dt[:10] if isinstance(admission_dt, str) else str(admission_dt)[:10]
            cond["recordedDate"] = cond["onsetDateTime"]

        if encounters:
            cond["encounter"] = {"reference": f"Encounter/{encounters[0].get('encounter_id', '')}"}

        conditions.append(cond)

    # --- Chronic conditions (from patient profile) ---
    chronic_list = record.get("patient", {}).get("chronic_conditions", [])
    for i, chronic in enumerate(chronic_list):
        if isinstance(chronic, str):
            c_code = chronic
            c_onset = ""
            c_severity = ""
        elif isinstance(chronic, dict):
            c_code = chronic.get("code", "")
            c_onset = chronic.get("onset_date", "")
            c_severity = chronic.get("severity", "")
        else:
            continue

        if not c_code:
            continue

        base = c_code.split(".")[0]
        if base in seen_codes:
            continue
        seen_codes.add(base)

        cond = {
            "resourceType": "Condition",
            "id": f"cond-{encounter_id}-chronic-{i:02d}" if encounter_id else f"cond-{patient_id}-chronic-{i:02d}",
            "clinicalStatus": {
                "coding": [{
                    "system": get_system_uri("hl7-condition-clinical"),
                    "code": "active",
                }],
            },
            "verificationStatus": {
                "coding": [{
                    "system": get_system_uri("hl7-condition-ver-status"),
                    "code": "confirmed",
                }],
            },
            "category": [{
                "coding": [{
                    "system": get_system_uri("hl7-condition-category"),
                    "code": "problem-list-item",
                    "display": _localize_display("Problem List Item", country, _CATEGORY_DISPLAY_JA),
                }],
            }],
            "code": _build_diagnosis_codeable_concept(
                _map_diagnosis_code(c_code, country), icd_system_key, country
            ),
            "subject": {"reference": f"Patient/{patient_id}"},
        }

        if c_severity:
            cond["severity"] = _severity_coding(c_severity, country)

        # Stage (NYHA, CKD G, GOLD, etc.)
        c_stage = chronic.get("stage", "") if isinstance(chronic, dict) else ""
        if c_stage:
            cond["stage"] = [{
                "summary": {"text": c_stage},
                "type": {
                    "coding": [{
                        "system": get_system_uri("snomed-ct"),
                        "code": "385356007",
                        "display": "Tumor stage finding",
                    }],
                    "text": "Clinical stage",
                },
            }]

        if c_onset:
            onset_str = c_onset if isinstance(c_onset, str) else str(c_onset)
            cond["onsetDateTime"] = onset_str[:10]

        # recordedDate: use admission date or onset, whichever is available
        if admission_dt:
            cond["recordedDate"] = (admission_dt[:10] if isinstance(admission_dt, str)
                                    else str(admission_dt)[:10])

        conditions.append(cond)

    return conditions
