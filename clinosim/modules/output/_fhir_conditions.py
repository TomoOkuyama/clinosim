"""FHIR R4 Condition resource builder (FA-1 conditions).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri, system_key_for
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key, is_us, resolve_lang
from clinosim.modules.output._fhir_common import (
    _build_diagnosis_codeable_concept,
    _coding_with_display,
    _infer_severity,
    _map_diagnosis_code,
    _severity_coding,
    to_fhir_date,
)
from clinosim.modules.output._fhir_localization import (
    _CATEGORY_DISPLAY_JA,
    _localize_display,
)

# Condition.stage.summary SNOMED coding for staging systems with an unambiguous,
# authoritatively-verified (tx.fhir.org $lookup) SNOMED CT concept. Keys are the
# exact stage strings produced by patient.activator._generate_stage — the drift
# guard test_every_generated_stage_is_mapped fails loud if activator adds a value
# without a code here (whitelist-drift bug class).
#
# Post-CO-6 (Chain 4, 2026-07-11): every stage system used by _generate_stage now
# has a verified SNOMED coding. Previously-text-only entries (GOLD 4, asthma
# severity 4-tier, hypertension stage 1-2, CCS angina I-III) verified via
# tx.fhir.org $lookup this session.
_STAGE_SUMMARY_SNOMED: dict[str, str] = {
    "CKD G1": "431855005",
    "CKD G2": "431856006",
    "CKD G3a": "700378005",
    "CKD G3b": "700379002",
    "CKD G4": "431857002",
    "CKD G5": "433146000",
    "NYHA I": "420300004",
    "NYHA II": "421704003",
    "NYHA III": "420913000",
    "NYHA IV": "422293003",
    # COPD severity — GOLD 1/2/3 verified session 42 (RM-4); GOLD 4 mapped
    # to SNOMED 135836000 "End stage COPD" (clinical equivalence; no distinct
    # "Very severe COPD" concept exists in SNOMED CT International Edition).
    "GOLD 1": "313296004",
    "GOLD 2": "313297008",
    "GOLD 3": "313299006",
    "GOLD 4": "135836000",
    # Asthma severity 4-tier (J45)
    "Mild intermittent":   "427679007",
    "Mild persistent":     "426979002",
    "Moderate persistent": "427295004",
    "Severe persistent":   "426656000",
    # Hypertension stage (I10) — Stage 1/2 per ACC/AHA 2017 boundaries
    "Stage 1": "827069000",
    "Stage 2": "827068008",
    # CCS angina class (I25) — Canadian Cardiovascular Society I-IV
    # (activator currently emits I/II/III only; IV registered forward-compat)
    "CCS I":   "61490001",
    "CCS II":  "41334000",
    "CCS III": "85284003",
    "CCS IV":  "89323001",
}


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
    # C4-05 / C4-07..09 (session 43 cycle 4): also index severity + stage so a
    # chronic-primary encounter-diagnosis can inherit them when _infer_severity
    # returns empty (routine outpatient follow-up with no physiological states).
    # Applies to essential HTN (I10) routine visits, DM/COPD/HF/CKD follow-ups —
    # 65.8% of I10 lacked severity because _infer_severity fell back to "" for
    # outpatient encounters.
    chronic_severity_by_base: dict[str, str] = {}
    chronic_stage_by_base: dict[str, str] = {}
    for _chronic in chronic_list:
        if isinstance(_chronic, str):
            _cc = _chronic
            _onset = ""
            _sev = ""
            _stg = ""
        else:
            # dict (production JSON path) or a ChronicCondition dataclass
            # (in-memory path) — get_attr_or_key handles both uniformly.
            _cc = get_attr_or_key(_chronic, "code", "")
            _onset = get_attr_or_key(_chronic, "onset_date", "") or ""
            _sev = get_attr_or_key(_chronic, "severity", "") or ""
            _stg = get_attr_or_key(_chronic, "stage", "") or ""
        if _cc:
            base = _cc.split(".")[0]
            chronic_onset_by_base.setdefault(base, _onset)
            chronic_severity_by_base.setdefault(base, _sev)
            chronic_stage_by_base.setdefault(base, _stg)

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
        # C4-05 (session 43 cycle 4): chronic-primary severity fallback.
        # _infer_severity returns "" when the encounter has no physiological
        # states (routine outpatient follow-up), leaving I10/E11/etc. Condition
        # without severity. Inherit from patient chronic_conditions severity
        # so problem-list severity is consistent with encounter-diagnosis.
        if not severity and is_chronic_primary:
            severity = chronic_severity_by_base.get(base_code, "")

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
            # C2-20 (session 42 cycle 2): JP Core Condition profile.
            **({"meta": {"profile": [
                "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Condition"
            ]}} if country_code == "JP" else {}),
            "clinicalStatus": {
                "coding": [_coding_with_display("hl7-condition-clinical", clinical_status, lang)],
            },
            "verificationStatus": {
                "coding": [_coding_with_display("hl7-condition-ver-status", "confirmed", lang)],
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

        # C4-07..10 (session 43 cycle 4): encounter-diagnosis stage inheritance.
        # When the primary dx is a staged chronic condition (DM/COPD/HF/CKD)
        # the encounter-diagnosis Condition should carry the same stage as the
        # patient's chronic entry. Otherwise E11/J44/I50 encounter-dx records
        # emit no stage while the sibling problem-list-item entry has stage
        # populated — inconsistent across the two Condition rows for the same
        # underlying disease.
        if is_chronic_primary:
            _stg = chronic_stage_by_base.get(base_code, "")
            if _stg:
                summary: dict[str, Any] = {"text": _stg}
                stage_snomed = _STAGE_SUMMARY_SNOMED.get(_stg)
                if stage_snomed:
                    summary["coding"] = [{
                        "system": get_system_uri("snomed-ct"),
                        "code": stage_snomed,
                        "display": code_lookup("snomed-ct", stage_snomed, resolve_lang(country)),
                    }]
                cond["stage"] = [{
                    "summary": summary,
                    "type": {"text": "Clinical stage"},
                }]

        if chronic_onset:
            # Chronic primary: onset is the disease onset date; recordedDate is the visit.
            cond["onsetDateTime"] = to_fhir_date(chronic_onset)
            if admission_dt:
                cond["recordedDate"] = to_fhir_date(admission_dt)
        elif admission_dt:
            cond["onsetDateTime"] = to_fhir_date(admission_dt)
            cond["recordedDate"] = cond["onsetDateTime"]

        if encounters:
            cond["encounter"] = {"reference": f"Encounter/{encounters[0].get('encounter_id', '')}"}
            # C2-31 (session 42 cycle 2): Condition.recorder ← attending physician
            # of the encounter. FHIR R4 R0..1; JP Core Condition recommends
            # this reference for chart traceability. Attending is emitted as
            # Practitioner in the encounter builder so this ref resolves.
            _att = encounters[0].get("attending_physician_id", "")
            if _att:
                cond["recorder"] = {"reference": f"Practitioner/{_att}"}

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
            # C4-02 (session 43 cycle 4): patient-scoped ID so the adapter's
            # write() dedup collapses per-encounter re-emissions. Was
            # `cond-{encounter_id}-chronic-{i}` which produced N duplicates
            # per patient (N = number of the patient's encounters), driving
            # cycle-3 RM-7 problem-list-item excess to 10x realistic count.
            "id": f"cond-chronic-{patient_id}-{i:02d}",
            # C2-20 (session 42): JP Core Condition profile also on chronic-
            # condition path (encounter-dx path handled above).
            **({"meta": {"profile": [
                "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Condition"
            ]}} if country_code == "JP" else {}),
            # C2-02/03 (session 42 cycle 2): use _coding_with_display so the
            # chronic-condition path also emits displays (was raw code).
            "clinicalStatus": {
                "coding": [_coding_with_display("hl7-condition-clinical", "active", lang)],
            },
            "verificationStatus": {
                "coding": [_coding_with_display("hl7-condition-ver-status", "confirmed", lang)],
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
        # in the branch above. The stage VALUE is carried by summary.text (always) plus
        # a summary.coding when the staging system has a verified SNOMED CT concept
        # (_STAGE_SUMMARY_SNOMED — CKD / NYHA). type.type is left as a plain-text label:
        # these are non-cancer clinical stages, so the former SNOMED 385356007 "Tumor
        # stage finding" coding was clinically wrong and is intentionally NOT emitted.
        if c_stage:
            summary: dict[str, Any] = {"text": c_stage}
            stage_snomed = _STAGE_SUMMARY_SNOMED.get(c_stage)
            if stage_snomed:
                summary["coding"] = [{
                    "system": get_system_uri("snomed-ct"),
                    "code": stage_snomed,
                    "display": code_lookup("snomed-ct", stage_snomed, resolve_lang(country)),
                }]
            cond["stage"] = [{
                "summary": summary,
                "type": {"text": "Clinical stage"},
            }]

        if c_onset:
            cond["onsetDateTime"] = to_fhir_date(c_onset)

        # C2-31 (session 42): Condition.recorder for chronic path as well.
        if encounters:
            _att = encounters[0].get("attending_physician_id", "")
            if _att:
                cond["recorder"] = {"reference": f"Practitioner/{_att}"}
        # recordedDate: use admission date or onset, whichever is available
        if admission_dt:
            cond["recordedDate"] = to_fhir_date(admission_dt)

        conditions.append(cond)

    return conditions
