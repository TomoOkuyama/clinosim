"""FHIR R4 Condition resource builder (FA-1 conditions).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri, system_key_for
from clinosim.modules._shared import get_attr_or_key, is_us, resolve_lang
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

    country_code = "US" if is_us(country) else "JP"
    lang = resolve_lang(country_code)
    icd_system_key = system_key_for("diagnosis", country_code)

    # Chronic conditions the patient carries — used both to recognise a chronic
    # primary diagnosis (active + chronic onset) and to emit problem-list items below.
    chronic_list = record.get("patient", {}).get("chronic_conditions", [])
    chronic_onset_by_base: dict[str, str] = {}
    for _chronic in chronic_list:
        if isinstance(_chronic, str):
            _cc = _chronic
            _onset = ""
        else:
            # dict (production JSON path) or a ChronicCondition dataclass
            # (in-memory path) — get_attr_or_key handles both uniformly.
            _cc = get_attr_or_key(_chronic, "code", "")
            _onset = get_attr_or_key(_chronic, "onset_date", "") or ""
        if _cc:
            chronic_onset_by_base.setdefault(_cc.split(".")[0], _onset)

    # --- Primary diagnosis (encounter diagnosis) ---
    dx_code = dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", "")
    if dx_code:
        base_code = dx_code.split(".")[0]
        seen_codes.add(base_code)

        # Determine severity from physiological states
        severity = _infer_severity(record)

        # A primary diagnosis that is one of the patient's chronic conditions
        # (e.g. an outpatient diabetes follow-up coding E11.9) is ongoing, not
        # resolved at the visit: mark it active with the chronic onset date.
        is_chronic_primary = base_code in chronic_onset_by_base
        chronic_onset = chronic_onset_by_base.get(base_code, "") if is_chronic_primary else ""

        # clinicalStatus: resolved if discharged alive, active if deceased (didn't resolve)
        if is_chronic_primary:
            clinical_status = "active"
        elif is_inpatient:
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

        if chronic_onset:
            # Chronic primary: onset is the disease onset date; recordedDate is the visit.
            onset_str = chronic_onset if isinstance(chronic_onset, str) else str(chronic_onset)
            cond["onsetDateTime"] = onset_str[:10]
            if admission_dt:
                cond["recordedDate"] = (admission_dt[:10] if isinstance(admission_dt, str)
                                        else str(admission_dt)[:10])
        elif admission_dt:
            cond["onsetDateTime"] = admission_dt[:10] if isinstance(admission_dt, str) else str(admission_dt)[:10]
            cond["recordedDate"] = cond["onsetDateTime"]

        if encounters:
            cond["encounter"] = {"reference": f"Encounter/{encounters[0].get('encounter_id', '')}"}

        conditions.append(cond)

    # --- Chronic conditions (from patient profile) ---
    for i, chronic in enumerate(chronic_list):
        if isinstance(chronic, str):
            c_code = chronic
            c_onset = ""
            c_severity = ""
            c_stage = ""
        else:
            # dict (production JSON path) or a ChronicCondition dataclass
            # (in-memory path) — get_attr_or_key handles both uniformly, so
            # a bare dataclass instance is no longer silently dropped.
            c_code = get_attr_or_key(chronic, "code", "")
            c_onset = get_attr_or_key(chronic, "onset_date", "")
            c_severity = get_attr_or_key(chronic, "severity", "")
            c_stage = get_attr_or_key(chronic, "stage", "")

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

        # Stage (NYHA class, CKD G, GOLD, hypertension Stage, CCS, etc.) — c_stage set
        # in the branch above. The stage VALUE is carried by summary.text. type.type is
        # left as a plain-text label only: these are non-cancer clinical stages/classes,
        # so the former SNOMED 385356007 "Tumor stage finding" coding was clinically
        # wrong on every one of them and is intentionally NOT emitted (no fabricated code).
        if c_stage:
            cond["stage"] = [{
                "summary": {"text": c_stage},
                "type": {"text": "Clinical stage"},
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
