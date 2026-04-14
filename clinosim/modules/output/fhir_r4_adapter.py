"""FHIR R4 adapter — Stage 3: convert CIF structural data to FHIR R4 Bundles.

Generates one FHIR Bundle (JSON) per patient containing:
  Patient, Encounter, Observation (labs + vitals), MedicationRequest, Practitioner references.
"""

from __future__ import annotations

import json
import os

from clinosim.codes import get_system_uri, lookup as code_lookup
from clinosim.locale.loader import load_code_mapping, load_reference_ranges, load_terminology
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Lazy-loaded drug name dictionary for Japanese localization
_drug_names_ja: dict[str, str] | None = None


def _load_drug_names_ja() -> dict[str, str]:
    """Load English→Japanese drug name mapping (case-insensitive keys)."""
    global _drug_names_ja
    if _drug_names_ja is not None:
        return _drug_names_ja
    import yaml
    yaml_path = Path(__file__).resolve().parent.parent.parent / "locale" / "shared" / "drug_names_ja.yaml"
    if yaml_path.exists():
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        _drug_names_ja = {k.lower(): v for k, v in raw.items()}
    else:
        _drug_names_ja = {}
    return _drug_names_ja


def _localize_drug_name(drug_name: str, country: str) -> str:
    """Resolve drug name to Japanese when country=JP.

    Matches drug names against the dictionary, handling:
    - Exact match (case-insensitive)
    - Dose suffix: "Drug 500mg" → "<ja> 500mg"
    - Category prefix: "category: Drug ..." → "<ja> ..."
    - Any drug name substring found anywhere in the text
    """
    if country == "US" or not drug_name:
        return drug_name
    ja_dict = _load_drug_names_ja()
    # Strip category prefix like "bronchodilator:" or "DVT_prophylaxis:"
    cleaned = drug_name
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1].strip()
    # Exact match (case-insensitive)
    ja = ja_dict.get(cleaned.lower())
    if ja:
        return ja
    # Match longest known drug name found anywhere in the cleaned text
    cleaned_lower = cleaned.lower()
    best_match: tuple[str, str] | None = None
    for en_key, ja_val in ja_dict.items():
        if en_key in cleaned_lower:
            if best_match is None or len(en_key) > len(best_match[0]):
                best_match = (en_key, ja_val)
    if best_match:
        # Replace the English drug name occurrence with Japanese
        en_key, ja_val = best_match
        # Case-insensitive replace (only first occurrence)
        idx = cleaned_lower.find(en_key)
        return (cleaned[:idx] + ja_val + cleaned[idx + len(en_key):]).strip()
    return drug_name


def convert_cif_to_fhir(
    cif_dir: str,
    output_dir: str,
    country: str = "US",
    narrative_version: str | None = None,
) -> None:
    """Read CIF structural data and write FHIR R4 Bulk Data Export NDJSON files.

    Output follows the HL7 FHIR Bulk Data Access spec:
    one NDJSON file per resource type (Patient.ndjson, Encounter.ndjson, etc.).
    Each line is a single FHIR resource (no Bundle wrapping).

    Args:
        cif_dir: path to a cif/ directory containing structural/ and
            (optionally) narratives/<version>/documents/.
        output_dir: directory to write the FHIR NDJSON files.
        country: "US" or "JP" — selects display language and code systems.
        narrative_version: if set, reads narrative CIF documents from
            cif_dir/narratives/<narrative_version>/documents/ and emits them
            as DocumentReference resources. When None (or "current"),
            the pointer at cif_dir/narratives/current_version.txt is used.
            When the directory does not exist, no DocumentReferences are
            emitted (graceful degradation).
    """
    os.makedirs(output_dir, exist_ok=True)

    structural_dir = os.path.join(cif_dir, "structural", "patients")
    if not os.path.exists(structural_dir):
        raise FileNotFoundError(f"CIF structural directory not found: {structural_dir}")

    # Resolve narrative version (current_version.txt pointer)
    narrative_docs_dir: str | None = None
    if narrative_version:
        if narrative_version == "current":
            current_link = os.path.join(cif_dir, "narratives", "current_version.txt")
            if os.path.exists(current_link):
                with open(current_link) as _f:
                    narrative_version = _f.read().strip()
        candidate = os.path.join(
            cif_dir, "narratives", narrative_version, "documents"
        )
        if os.path.isdir(candidate):
            narrative_docs_dir = candidate

    # Load hospital data (Practitioner roster + Organization/Location config)
    roster_map: dict[str, dict] = {}
    hospital_config: dict = {}
    hospital_path = os.path.join(cif_dir, "hospital.json")
    if os.path.exists(hospital_path):
        with open(hospital_path) as f:
            hospital_data = json.load(f)
        for staff in hospital_data.get("staff", []):
            roster_map[staff.get("staff_id", "")] = staff
        hospital_config = hospital_data.get("config", {}) or {}

    # Open NDJSON file handles for each resource type
    # Use a writer cache to lazy-create files only for types we encounter
    writers: dict[str, Any] = {}
    written_ids: dict[str, set[str]] = {}  # de-dup Patient and Practitioner

    def write(resource: dict) -> None:
        rt = resource.get("resourceType", "")
        if not rt:
            return
        # Dedup for patient-level master resources
        # AllergyIntolerance is patient-level (lifelong), not per-encounter
        if rt in ("Patient", "Practitioner", "PractitionerRole",
                  "Organization", "Location", "AllergyIntolerance"):
            ids = written_ids.setdefault(rt, set())
            rid = resource.get("id", "")
            if rid in ids:
                return
            ids.add(rid)
        if rt not in writers:
            path = os.path.join(output_dir, f"{rt}.ndjson")
            writers[rt] = open(path, "w", encoding="utf-8")
        writers[rt].write(json.dumps(resource, ensure_ascii=False) + "\n")

    try:
        # Master resources (Organization + Location) — written once
        facility_bundle = _build_facility_bundle(hospital_config, country)
        for entry in facility_bundle.get("entry", []):
            write(entry["resource"])

        # Walk patient records, build per-record FHIR resources, write each line
        for filename in sorted(os.listdir(structural_dir)):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(structural_dir, filename)) as f:
                record = json.load(f)

            bundle = _build_bundle(record, country, roster_map, hospital_config)
            for entry in bundle.get("entry", []):
                write(entry["resource"])

            # === DocumentReference resources (narrative CIF) ===
            if narrative_docs_dir:
                enc_id = (
                    (record.get("encounters") or [{}])[0].get("encounter_id", "")
                )
                if enc_id:
                    enc_docs_dir = os.path.join(narrative_docs_dir, enc_id)
                    if os.path.isdir(enc_docs_dir):
                        patient_id = (
                            record.get("patient", {}).get("patient_id", "")
                        )
                        for doc_file in sorted(os.listdir(enc_docs_dir)):
                            if not doc_file.endswith(".json"):
                                continue
                            with open(
                                os.path.join(enc_docs_dir, doc_file),
                                encoding="utf-8",
                            ) as df:
                                doc_data = json.load(df)
                            docref = _build_document_reference(
                                doc_data, patient_id, country
                            )
                            if docref:
                                write(docref)

        # Manifest (FHIR Bulk Data spec)
        request_desc = f"clinosim generate (country={country})"
        if narrative_version:
            request_desc += f" narrative={narrative_version}"
        manifest = {
            "transactionTime": datetime.now().isoformat(),
            "request": request_desc,
            "requiresAccessToken": False,
            "output": [
                {"type": rt, "url": f"{rt}.ndjson"}
                for rt in sorted(writers.keys())
            ],
            "error": [],
        }
        with open(os.path.join(output_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
    finally:
        for w in writers.values():
            w.close()


_DEPT_DISPLAY_JA: dict[str, str] = {
    "internal_medicine": "内科",
    "cardiology": "循環器内科",
    "pulmonology": "呼吸器内科",
    "gastroenterology": "消化器内科",
    "nephrology": "腎臓内科",
    "endocrinology": "内分泌・代謝内科",
    "neurology": "神経内科",
    "general_surgery": "外科",
    "orthopedics": "整形外科",
    "neurosurgery": "脳神経外科",
    "trauma_surgery": "外傷外科",
    "emergency_medicine": "救急科",
    "primary_care": "総合診療科",
    "obstetrics_gynecology": "産婦人科",
    "pediatrics": "小児科",
    "ophthalmology": "眼科",
    "psychiatry": "精神科",
    "radiology": "放射線科",
    "rehabilitation": "リハビリテーション科",
}


def _build_facility_bundle(hospital_config: dict, country: str) -> dict:
    """Build a FHIR Bundle containing Organization + Location for the hospital."""
    entries: list[dict] = []
    available = hospital_config.get("available_departments", []) or []
    wards_map = hospital_config.get("wards", {}) or {}
    beds = hospital_config.get("resource_capacity", {}).get("inpatient_beds", 0)

    # Root hospital Organization
    hosp_name = "Community Hospital" if country != "JP" else "総合病院"
    root_org = {
        "resourceType": "Organization",
        "id": "hospital-main",
        "active": True,
        "type": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/organization-type",
                "code": "prov",
                "display": "Healthcare Provider",
            }],
        }],
        "name": hosp_name,
        "alias": [f"{beds}-bed hospital"] if beds else [],
    }
    entries.append(_entry(root_org))

    # Department Organizations (one per available_department)
    for dept in available:
        display = _DEPT_DISPLAY_JA.get(dept, dept.replace("_", " ").title()) \
            if country == "JP" else dept.replace("_", " ").title()
        dept_org = {
            "resourceType": "Organization",
            "id": f"dept-{dept.replace('_', '-')}",
            "active": True,
            "type": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/organization-type",
                    "code": "dept",
                    "display": "Hospital Department",
                }],
            }],
            "name": display,
            "partOf": {"reference": "Organization/hospital-main"},
        }
        entries.append(_entry(dept_org))

    # Ward Location resources + Bed Locations (partOf ward)
    ward_capacity = hospital_config.get("ward_capacity", {}) or {}
    seen_wards: set[str] = set()
    for dept, ward_list in wards_map.items():
        for ward in ward_list:
            if ward in seen_wards:
                continue
            seen_wards.add(ward)
            phys_type = "wa"  # Ward
            phys_display = "Ward"
            if ward == "ER":
                phys_type = "area"
                phys_display = "Emergency Room"
            elif ward == "OPD":
                phys_type = "area"
                phys_display = "Outpatient Clinic"
            org_ref = f"Organization/dept-{dept.replace('_', '-')}"
            ward_loc = {
                "resourceType": "Location",
                "id": f"loc-ward-{ward}",
                "status": "active",
                "name": (f"{ward}病棟" if country == "JP" else f"Ward {ward}") if ward not in ("ER", "OPD") else phys_display,
                "physicalType": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/location-physical-type",
                        "code": phys_type,
                        "display": phys_display,
                    }],
                },
                "managingOrganization": {"reference": org_ref},
            }
            entries.append(_entry(ward_loc))

            # Bed Location resources for inpatient wards
            if ward not in ("ER", "OPD"):
                bed_count = ward_capacity.get(ward, 0)
                for bed_idx in range(1, bed_count + 1):
                    bed_id = f"{ward}-{bed_idx:02d}"
                    bed_loc = {
                        "resourceType": "Location",
                        "id": f"loc-bed-{bed_id}",
                        "status": "active",
                        "name": f"{bed_id}号室" if country == "JP" else f"Bed {bed_id}",
                        "physicalType": {
                            "coding": [{
                                "system": "http://terminology.hl7.org/CodeSystem/location-physical-type",
                                "code": "bd",
                                "display": "Bed",
                            }],
                        },
                        "partOf": {"reference": f"Location/loc-ward-{ward}"},
                        "managingOrganization": {"reference": org_ref},
                    }
                    entries.append(_entry(bed_loc))

    # Operating room Location resources
    n_or = int((hospital_config.get("resource_capacity") or {}).get("operating_rooms", 0))
    if n_or > 0:
        # Associate OR with general_surgery department if available, else root
        or_org_ref = (
            "Organization/dept-general-surgery"
            if "general_surgery" in available
            else "Organization/hospital-main"
        )
        for i in range(1, n_or + 1):
            or_loc = {
                "resourceType": "Location",
                "id": f"loc-or-{i}",
                "status": "active",
                "name": (f"手術室 {i}" if country == "JP" else f"Operating Room {i}"),
                "physicalType": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/location-physical-type",
                        "code": "ro",
                        "display": "Room",
                    }],
                },
                "type": [{
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                        "code": "OR",
                        "display": "Operating Room",
                    }],
                }],
                "managingOrganization": {"reference": or_org_ref},
            }
            entries.append(_entry(or_loc))

    return {
        "resourceType": "Bundle",
        "id": "facility",
        "type": "collection",
        "timestamp": datetime.now().isoformat(),
        "entry": entries,
    }


def _build_bundle(
    record: dict, country: str,
    roster_map: dict[str, dict] | None = None,
    hospital_config: dict | None = None,
) -> dict:
    """Build a FHIR R4 Bundle from a CIF patient record."""
    if roster_map is None:
        roster_map = {}
    if hospital_config is None:
        hospital_config = {}
    patient_data = record.get("patient", {})
    patient_id = patient_data.get("patient_id", "unknown")

    entries: list[dict] = []

    # === Patient resource ===
    entries.append(_entry(_build_patient(patient_data, country)))

    # === Encounter resources ===
    is_readmission = record.get("is_readmission", False)
    prior_encounter_id = record.get("prior_encounter_id")
    dx = record.get("clinical_diagnosis", {})
    primary_dx_code = dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", "")
    admit_dx_code = dx.get("admission_diagnosis_code", "")
    admit_dx_system = dx.get("admission_diagnosis_system", "icd-10-cm")
    for enc in record.get("encounters", []):
        entries.append(_entry(
            _build_encounter(enc, patient_id, is_readmission, prior_encounter_id,
                             primary_dx_code=primary_dx_code, country=country,
                             admit_dx_code=admit_dx_code, admit_dx_system=admit_dx_system)
        ))

    # === Condition resources ===
    entries.extend(
        _entry(c) for c in _build_conditions(record, patient_id, country)
    )

    # === AllergyIntolerance resources ===
    for i, allergy in enumerate(patient_data.get("allergies", []) or []):
        if isinstance(allergy, dict):
            ai = _build_allergy_intolerance(allergy, patient_id, i, country)
            if ai:
                entries.append(_entry(ai))

    # Primary encounter id (for back-references)
    primary_enc_id = (record.get("encounters", [{}])[0].get("encounter_id", "")
                      if record.get("encounters") else "")

    # === Observation resources — Lab results ===
    patient_sex = patient_data.get("sex", "")
    for i, order in enumerate(record.get("orders", [])):
        if order.get("order_type") == "lab" and order.get("result"):
            result = order["result"]
            obs = _build_lab_observation(order, result, patient_id, i, country,
                                          patient_sex, primary_enc_id)
            if obs:
                entries.append(_entry(obs))

    # === Observation resources — Vital signs ===
    for i, vs in enumerate(record.get("vital_signs", [])):
        entries.extend(_build_vital_observations(vs, patient_id, i, country, primary_enc_id))

    # === MedicationRequest resources ===
    for order in record.get("orders", []):
        if order.get("order_type") == "medication":
            entries.append(_entry(_build_medication_request(
                order, patient_id, country, primary_enc_id, primary_dx_code,
            )))

    # === MedicationAdministration resources (MAR) ===
    for i, mar in enumerate(record.get("medication_administrations", [])):
        entries.append(_entry(_build_medication_admin(
            mar, patient_id, i, country,
            encounter_id=primary_enc_id, primary_dx_code=primary_dx_code,
        )))

    # === Procedure resources ===
    for i, proc in enumerate(record.get("procedures", [])):
        entries.append(_entry(_build_procedure(proc, patient_id, i, country)))

    # === Practitioner + PractitionerRole resources (deduplicated) ===
    seen_staff: set[str] = set()

    def _add_staff(staff_id: str) -> None:
        if not staff_id or staff_id in seen_staff:
            return
        seen_staff.add(staff_id)
        entries.append(_entry(_build_practitioner(staff_id, roster_map, country=country)))
        role = _build_practitioner_role(staff_id, roster_map)
        if role:
            entries.append(_entry(role))

    for enc in record.get("encounters", []):
        _add_staff(enc.get("attending_physician_id", ""))
        _add_staff(enc.get("admitting_physician_id", ""))
        _add_staff(enc.get("discharging_physician_id", ""))
    for o in record.get("orders", []):
        _add_staff(o.get("ordered_by", ""))
        if o.get("result"):
            _add_staff(o["result"].get("performed_by", ""))
    for vs in record.get("vital_signs", []):
        _add_staff(vs.get("measured_by", ""))
    for mar in record.get("medication_administrations", []):
        _add_staff(mar.get("administered_by", ""))
    for proc in record.get("procedures", []):
        _add_staff(proc.get("primary_surgeon_id", ""))
        _add_staff(proc.get("anesthesiologist_id", ""))

    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "collection",
        "timestamp": datetime.now().isoformat(),
        "entry": entries,
    }


def _entry(resource: dict) -> dict:
    """Wrap a resource as a Bundle entry."""
    rid = resource.get("id", str(uuid.uuid4()))
    rtype = resource.get("resourceType", "Resource")
    return {
        "fullUrl": f"urn:uuid:{rid}",
        "resource": resource,
    }


# ============================================================
# Resource builders
# ============================================================

def _build_patient(p: dict, country: str) -> dict:
    """Build FHIR Patient resource with locale-aware name."""
    # Extract name from patient profile
    name_data = p.get("name", {})
    family = name_data.get("family_name", p.get("patient_id", ""))
    given = name_data.get("given_name", "")

    gender = "female" if p.get("sex") == "F" else "male"
    dob = p.get("date_of_birth")

    # Build FHIR HumanName
    fhir_name: dict[str, Any] = {"family": family, "given": [given]}
    phonetic = name_data.get("phonetic")
    if phonetic and country == "JP":
        # JP: add phonetic representation (katakana)
        fhir_name["extension"] = [{
            "url": "http://hl7.org/fhir/StructureDefinition/iso21090-EN-representation",
            "valueString": "SYL",
        }]

    pid = p.get("patient_id", str(uuid.uuid4()))
    # Hospital MRN identifier system (country-specific)
    mrn_system = (
        "urn:oid:1.2.392.100495.20.3.51.1"  # JP example MRN OID
        if country == "JP"
        else "http://hospital.example.org/identifiers/mrn"
    )
    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": pid,
        "identifier": [{
            "use": "usual",
            "type": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                    "code": "MR",
                    "display": "Medical Record Number",
                }],
                "text": "MRN" if country != "JP" else "診療録番号",
            },
            "system": mrn_system,
            "value": pid,
            "assigner": {"reference": "Organization/hospital-main"},
        }],
        "active": True,
        "name": [fhir_name],
        "gender": gender,
    }

    if dob:
        resource["birthDate"] = dob if isinstance(dob, str) else str(dob)

    # Extensions for blood type
    if p.get("blood_type"):
        resource["extension"] = [{
            "url": "http://hl7.org/fhir/StructureDefinition/patient-bloodType",
            "valueString": f"{p['blood_type']}{p.get('rh_factor', '+')}",
        }]

    # Address
    addr = p.get("address")
    if addr and isinstance(addr, dict):
        fhir_addr = _build_address(addr, country)
        if fhir_addr:
            resource["address"] = [fhir_addr]

    # Telecom (phone)
    contact = p.get("contact")
    if contact and isinstance(contact, dict):
        telecoms = _build_telecom(contact)
        if telecoms:
            resource["telecom"] = telecoms

    # Marital status
    marital = p.get("marital_status", "")
    if marital:
        resource["maritalStatus"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus",
                "code": marital,
                "display": (_MARITAL_DISPLAY_JA if country == "JP" else _MARITAL_DISPLAY).get(marital, ""),
            }],
        }

    # Communication / preferred language
    lang = p.get("preferred_language", "")
    if lang:
        resource["communication"] = [{
            "language": {
                "coding": [{
                    "system": "urn:ietf:bcp:47",
                    "code": lang,
                    "display": _LANG_DISPLAY.get(lang, lang),
                }],
            },
            "preferred": True,
        }]

    # Emergency contact
    if contact and isinstance(contact, dict):
        emer_name = contact.get("emergency_contact_name", "")
        emer_phone = contact.get("emergency_contact_phone", "")
        emer_rel = contact.get("emergency_contact_relationship", "")
        if emer_name or emer_phone:
            ec: dict[str, Any] = {}
            if emer_rel:
                ec["relationship"] = [{
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0131",
                        "code": "C",
                        "display": "Emergency Contact",
                    }],
                    "text": emer_rel,
                }]
            if emer_name:
                ec["name"] = {"text": emer_name}
            if emer_phone:
                ec["telecom"] = [{
                    "system": "phone", "value": emer_phone, "use": "mobile",
                }]
            resource["contact"] = [ec]

    return resource


_MARITAL_DISPLAY = {
    "S": "Never Married", "M": "Married", "D": "Divorced",
    "W": "Widowed", "U": "Unmarried", "T": "Domestic partner",
}
_MARITAL_DISPLAY_JA = {
    "S": "未婚", "M": "既婚", "D": "離婚",
    "W": "死別", "U": "未婚", "T": "事実婚",
}

_LANG_DISPLAY = {
    "en-US": "English (US)",
    "ja-JP": "Japanese (Japan)",
}


# ============================================================
# AllergyIntolerance
# ============================================================

_ALLERGEN_RXNORM: dict[str, str] = {
    # RxNorm ingredient codes for common drug allergens
    "Penicillin": "7980",
    "Sulfonamide": "10180",
    "NSAIDs": "5640",  # ibuprofen as representative
    "Cephalosporin": "2173",
    "Aspirin": "1191",
}


def _build_allergy_intolerance(
    allergy: dict, patient_id: str, index: int, country: str,
) -> dict | None:
    """Build FHIR AllergyIntolerance from CIF allergy data."""
    substance = allergy.get("substance", "")
    if not substance:
        return None

    rxnorm = _ALLERGEN_RXNORM.get(substance, "")
    code: dict[str, Any] = {"text": substance}
    if rxnorm:
        code["coding"] = [{
            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
            "code": rxnorm,
            "display": substance,
        }]

    severity = allergy.get("severity", "mild").lower()
    criticality = "high" if severity == "severe" else "low"

    reaction_type = allergy.get("reaction_type", "")
    reaction: dict[str, Any] = {"severity": severity}
    if reaction_type:
        reaction["manifestation"] = [{
            "text": reaction_type,
        }]

    return {
        "resourceType": "AllergyIntolerance",
        "id": f"allergy-{patient_id}-{index:02d}",  # patient-scoped is OK (allergies are patient-level)
        "clinicalStatus": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                "code": "active",
                "display": "Active",
            }],
        },
        "verificationStatus": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                "code": "confirmed",
                "display": "Confirmed",
            }],
        },
        "type": "allergy",
        "category": ["medication"],
        "criticality": criticality,
        "code": code,
        "patient": {"reference": f"Patient/{patient_id}"},
        "reaction": [reaction],
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

    country_code = "JP" if country != "US" else "US"
    lang = "ja" if country_code == "JP" else "en"
    icd_system_key = "icd-10" if country_code == "JP" else "icd-10-cm"

    # --- Primary diagnosis (encounter diagnosis) ---
    dx_code = dx.get("discharge_diagnosis_code") or dx.get("admission_diagnosis_code", "")
    # Display text comes from the codes module (not stored in CIF)
    dx_name = code_lookup(icd_system_key, dx_code, lang) if dx_code else ""
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

        display = dx_name or dx_code
        icd_system = get_system_uri(icd_system_key)

        cond: dict[str, Any] = {
            "resourceType": "Condition",
            "id": f"cond-{encounter_id}-primary" if encounter_id else f"cond-{patient_id}-primary",
            "clinicalStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": clinical_status,
                }],
            },
            "verificationStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                }],
            },
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                    "code": "encounter-diagnosis",
                    "display": "Encounter Diagnosis",
                }],
            }],
            "code": {
                "coding": [{"system": icd_system, "code": dx_code, "display": display}],
                "text": display,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
        }

        if severity:
            cond["severity"] = _severity_coding(severity)

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

        display = code_lookup(icd_system_key, c_code, lang) or c_code
        icd_system = get_system_uri(icd_system_key)

        cond = {
            "resourceType": "Condition",
            "id": f"cond-{encounter_id}-chronic-{i:02d}" if encounter_id else f"cond-{patient_id}-chronic-{i:02d}",
            "clinicalStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                }],
            },
            "verificationStatus": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                }],
            },
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                    "code": "problem-list-item",
                    "display": "Problem List Item",
                }],
            }],
            "code": {
                "coding": [{"system": icd_system, "code": c_code, "display": display}],
                "text": display,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
        }

        if c_severity:
            cond["severity"] = _severity_coding(c_severity)

        # Stage (NYHA, CKD G, GOLD, etc.)
        c_stage = chronic.get("stage", "") if isinstance(chronic, dict) else ""
        if c_stage:
            cond["stage"] = [{
                "summary": {"text": c_stage},
                "type": {
                    "coding": [{
                        "system": "http://snomed.info/sct",
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


def _infer_severity(record: dict) -> str:
    """Infer encounter severity from physiological states."""
    states = record.get("physiological_states", [])
    if not states:
        return ""
    # Use peak inflammation as severity proxy
    peak_infl = max(s.get("inflammation_level", 0) for s in states)
    if peak_infl >= 0.5:
        return "severe"
    elif peak_infl >= 0.2:
        return "moderate"
    elif peak_infl > 0:
        return "mild"
    return ""


_SEVERITY_SNOMED: dict[str, dict[str, str]] = {
    "mild": {"code": "255604002", "display": "Mild"},
    "moderate": {"code": "6736007", "display": "Moderate"},
    "severe": {"code": "24484000", "display": "Severe"},
}


def _severity_coding(severity: str) -> dict[str, Any]:
    """Build FHIR severity CodeableConcept from severity string."""
    sev = severity.lower()
    snomed = _SEVERITY_SNOMED.get(sev, _SEVERITY_SNOMED.get("moderate"))
    return {
        "coding": [{
            "system": "http://snomed.info/sct",
            **snomed,
        }],
    }


# JIS X 0401 prefecture codes
_PREFECTURE_CODE: dict[str, str] = {
    "北海道": "01", "青森県": "02", "岩手県": "03", "宮城県": "04", "秋田県": "05",
    "山形県": "06", "福島県": "07", "茨城県": "08", "栃木県": "09", "群馬県": "10",
    "埼玉県": "11", "千葉県": "12", "東京都": "13", "神奈川県": "14", "新潟県": "15",
    "富山県": "16", "石川県": "17", "福井県": "18", "山梨県": "19", "長野県": "20",
    "岐阜県": "21", "静岡県": "22", "愛知県": "23", "三重県": "24", "滋賀県": "25",
    "京都府": "26", "大阪府": "27", "兵庫県": "28", "奈良県": "29", "和歌山県": "30",
    "鳥取県": "31", "島根県": "32", "岡山県": "33", "広島県": "34", "山口県": "35",
    "徳島県": "36", "香川県": "37", "愛媛県": "38", "高知県": "39", "福岡県": "40",
    "佐賀県": "41", "長崎県": "42", "熊本県": "43", "大分県": "44", "宮崎県": "45",
    "鹿児島県": "46", "沖縄県": "47",
}

# US state abbreviation to FIPS code (common ones)
_US_STATE_CODE: dict[str, str] = {
    "MA": "25", "NY": "36", "CA": "06", "TX": "48", "FL": "12", "IL": "17",
    "PA": "42", "OH": "39", "GA": "13", "NC": "37", "MI": "26", "NJ": "34",
}


def _build_address(addr: dict, country: str) -> dict[str, Any] | None:
    """Build FHIR Address from CIF address data."""
    if not addr.get("city") and not addr.get("line1"):
        return None

    state_name = addr.get("state", "")
    country_code = addr.get("country", country)

    # Build full address line
    if country_code == "JP":
        # JP: 都道府県+市区町村+番地
        line = f"{state_name}{addr.get('city', '')}{addr.get('line1', '')}"
    else:
        # US: street line
        line = addr.get("line1", "")

    fhir_addr: dict[str, Any] = {
        "type": "both",
        "line": [line] if line else [],
        "city": addr.get("city", ""),
        "postalCode": addr.get("postal_code", ""),
        "country": country_code,
    }

    # State: use code for JP (JIS X 0401), abbreviation for US
    if country_code == "JP":
        code = _PREFECTURE_CODE.get(state_name, "")
        if code:
            fhir_addr["state"] = code
    elif state_name:
        fhir_addr["state"] = state_name

    return fhir_addr


def _build_telecom(contact: dict) -> list[dict[str, str]]:
    """Build FHIR ContactPoint list from CIF contact data."""
    telecoms: list[dict[str, str]] = []
    if contact.get("phone_mobile"):
        telecoms.append({
            "system": "phone", "value": contact["phone_mobile"], "use": "mobile",
        })
    if contact.get("phone_home") and contact["phone_home"] != contact.get("phone_mobile"):
        telecoms.append({
            "system": "phone", "value": contact["phone_home"], "use": "home",
        })
    if contact.get("email"):
        telecoms.append({
            "system": "email", "value": contact["email"], "use": "home",
        })
    return telecoms


_ENCOUNTER_TYPE_SNOMED: dict[str, dict[str, str]] = {
    "inpatient": {"code": "32485007", "display": "Hospital admission"},
    "emergency": {"code": "50849002", "display": "Emergency hospital admission"},
    "outpatient": {"code": "270427003", "display": "Patient-initiated encounter"},
    "icu": {"code": "183452005", "display": "Emergency hospital admission"},
}
_ENCOUNTER_TYPE_SNOMED_JA: dict[str, str] = {
    "inpatient": "入院",
    "emergency": "救急入院",
    "outpatient": "外来受診",
    "icu": "救急入院",
}

_DEPARTMENT_DISPLAY: dict[str, str] = {
    "internal_medicine": "Internal Medicine",
    "cardiology": "Cardiology",
    "pulmonology": "Pulmonology",
    "gastroenterology": "Gastroenterology",
    "nephrology": "Nephrology",
    "endocrinology": "Endocrinology",
    "neurology": "Neurology",
    "general_surgery": "General Surgery",
    "orthopedics": "Orthopedic Surgery",
    "emergency_medicine": "Emergency Medicine",
}


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
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": class_code,
            "display": class_display,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
    }

    # Type (SNOMED)
    type_info = _ENCOUNTER_TYPE_SNOMED.get(enc_type)
    if type_info:
        coding = {"system": "http://snomed.info/sct", **type_info}
        if country == "JP" and enc_type in _ENCOUNTER_TYPE_SNOMED_JA:
            coding["display"] = _ENCOUNTER_TYPE_SNOMED_JA[enc_type]
        resource["type"] = [{"coding": [coding]}]

    # Priority (Encounter.priority)
    priority = enc.get("priority", "")
    if priority:
        priority_display = {"EM": "emergency", "UR": "urgent", "R": "routine"}.get(priority, "")
        resource["priority"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActPriority",
                "code": priority,
                "display": priority_display,
            }],
        }

    # Service type (department)
    department = enc.get("department_id", "") or "internal_medicine"
    resource["serviceType"] = {
        "coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/service-type",
            "code": department,
            "display": (_DEPT_DISPLAY_JA if country == "JP" else _DEPARTMENT_DISPLAY).get(department, department),
        }],
        "text": (_DEPT_DISPLAY_JA if country == "JP" else _DEPARTMENT_DISPLAY).get(department, department),
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
                    "system": "http://unitsofmeasure.org",
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
                    "system": "http://terminology.hl7.org/CodeSystem/diagnosis-role",
                    "code": "DD",
                    "display": "Discharge diagnosis",
                }],
            },
            "rank": 1,
        }]

    # Hospitalization (admit source / discharge disposition)
    hosp: dict[str, Any] = {}
    if enc.get("admit_source"):
        hosp["admitSource"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/admit-source",
                "code": enc["admit_source"],
            }],
        }
    if enc.get("discharge_disposition"):
        hosp["dischargeDisposition"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/discharge-disposition",
                "code": enc["discharge_disposition"],
            }],
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
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "READM",
                    "display": "Readmission",
                }],
            })
        else:
            resource["type"] = [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "READM",
                    "display": "Readmission",
                }],
            }]

    return resource


def _make_participant(code: str, display: str, practitioner_id: str) -> dict[str, Any]:
    """Build an Encounter.participant entry."""
    return {
        "type": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                "code": code,
                "display": display,
            }],
        }],
        "individual": {"reference": f"Practitioner/{practitioner_id}"},
    }


def _build_lab_observation(
    order: dict, result: dict, patient_id: str, index: int,
    country: str, patient_sex: str = "", encounter_id: str = "",
) -> dict | None:
    """Build FHIR Observation resource for a lab result."""
    value = result.get("value")
    if value is None:
        return None

    lab_name = order.get("display_name", "Unknown")

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
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "laboratory",
                "display": "Laboratory",
            }],
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
            "system": "http://unitsofmeasure.org",
            "code": unit_str,  # UCUM code identical to display unit
        }
    else:
        resource["valueString"] = str(value)

    # Interpretation flag (always set, default Normal)
    flag = result.get("flag")
    interp_map = {
        "H": {"code": "H", "display": "High"},
        "L": {"code": "L", "display": "Low"},
        "H*": {"code": "HH", "display": "Critical high"},
        "L*": {"code": "LL", "display": "Critical low"},
        "critical": {"code": "AA", "display": "Critical abnormal"},
    }
    coded = interp_map.get(flag) if flag else {"code": "N", "display": "Normal"}
    resource["interpretation"] = [{
        "coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
            **coded,
        }],
    }]

    # Reference range (JP: JCCLS共用基準範囲)
    ref_range = _build_reference_range(lab_name, patient_sex, country_code)
    if ref_range:
        resource["referenceRange"] = ref_range

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
    # time_offset: per-field realistic delay within a vital-sign set
    # BP/HR measured simultaneously (same device cycle), Temp added later, RR counted last
    _vital_map = [
        ("heart_rate", "8867-4", "Heart rate", "脈拍", "/min", 60, 100, 40, 130, 0),
        ("systolic_bp", "8480-6", "Systolic blood pressure", "収縮期血圧", "mm[Hg]", 90, 140, 80, 200, 0),
        ("diastolic_bp", "8462-4", "Diastolic blood pressure", "拡張期血圧", "mm[Hg]", 60, 90, 50, 120, 0),
        ("spo2", "2708-6", "Oxygen saturation", "酸素飽和度", "%", 95, 100, 88, 100, 5),
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
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "vital-signs",
                    "display": "Vital Signs",
                }],
            }],
            "code": {
                "coding": [{"system": "http://loinc.org", "code": loinc, "display": display}],
                "text": display,
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "valueQuantity": {
                "value": value,
                "unit": unit,
                "system": "http://unitsofmeasure.org",
                "code": unit,
            },
        }
        # Add timestamp with per-field offset (BP/HR same, Temp +30s, RR +60s, SpO2 +5s)
        timestamp = vs.get("timestamp")
        if timestamp:
            try:
                from datetime import datetime as _dt, timedelta as _td
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

        # Reference range
        obs["referenceRange"] = [{
            "low": {"value": low, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
            "high": {"value": high, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
            "type": {
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/referencerange-meaning",
                    "code": "normal",
                    "display": "Normal Range",
                }],
            },
            "text": "Normal adult range",
        }]

        # Interpretation (compute from value vs reference range)
        interp_code = "N"
        interp_display = "Normal"
        if value <= crit_low:
            interp_code = "LL"; interp_display = "Critical low"
        elif value >= crit_high:
            interp_code = "HH"; interp_display = "Critical high"
        elif value < low:
            interp_code = "L"; interp_display = "Low"
        elif value > high:
            interp_code = "H"; interp_display = "High"
        obs["interpretation"] = [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                "code": interp_code,
                "display": interp_display,
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
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "vital-signs",
                    "display": "Vital Signs",
                }],
            }],
            "code": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": "80288-4",
                    "display": "Level of consciousness AVPU",
                }],
                "text": "意識レベル (AVPU)" if country == "JP" else "Level of consciousness (AVPU)",
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "valueCodeableConcept": {
                "coding": [{
                    "system": "http://snomed.info/sct",
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
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "vital-signs",
                    "display": "Vital Signs",
                }],
            }],
            "code": {
                "coding": [{
                    "system": "http://loinc.org",
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
                "system": "http://unitsofmeasure.org",
                "code": "L/min",
            }
        if device:
            o2_obs["component"] = [{
                "code": {
                    "coding": [{
                        "system": "http://loinc.org",
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


_ROUTE_SNOMED: dict[str, dict[str, str]] = {
    "PO": {"code": "26643006", "display": "Oral"},
    "IV": {"code": "47625008", "display": "Intravenous"},
    "SC": {"code": "34206005", "display": "Subcutaneous"},
    "IM": {"code": "78421000", "display": "Intramuscular"},
    "SL": {"code": "37161004", "display": "Sublingual"},
    "PR": {"code": "37161004", "display": "Per rectum"},
    "INHALED": {"code": "447694001", "display": "Inhalation"},
    "TOPICAL": {"code": "6064005", "display": "Topical"},
    "NEBULIZED": {"code": "447694001", "display": "Inhalation"},
}


_ROUTE_JA: dict[str, str] = {
    "PO": "経口", "IV": "静注", "SC": "皮下注", "IM": "筋注",
    "SL": "舌下", "PR": "直腸", "INH": "吸入", "TOPICAL": "外用",
    "NG": "経鼻", "INHALED": "吸入",
}
_FREQ_JA: dict[str, str] = {
    "DAILY": "1日1回", "BID": "1日2回", "TID": "1日3回", "QID": "1日4回",
    "Q4H": "4時間毎", "Q6H": "6時間毎", "Q8H": "8時間毎", "Q12H": "12時間毎",
    "PRN": "必要時", "STAT": "緊急", "ONCE": "1回",
    "1x/day": "1日1回", "2x/day": "1日2回", "3x/day": "1日3回", "4x/day": "1日4回",
}


def _build_dosage_instruction(order: dict, country: str = "US") -> dict[str, Any] | None:
    """Build FHIR Dosage from structured order fields."""
    dose_qty = order.get("dose_quantity")
    dose_unit = order.get("dose_unit", "")
    freq = order.get("frequency", "")
    freq_per_day = order.get("frequency_per_day")
    route = (order.get("route") or "").upper()

    # If nothing structured is available, fall back to text from display_name
    if dose_qty is None and not freq and not route:
        text = order.get("display_name", "")
        if text:
            return {"text": text}
        return None

    dosage: dict[str, Any] = {}
    parts = []

    # Dose quantity
    if dose_qty is not None and dose_unit:
        dosage["doseAndRate"] = [{
            "doseQuantity": {
                "value": dose_qty,
                "unit": dose_unit,
                "system": "http://unitsofmeasure.org",
            },
        }]
        parts.append(f"{dose_qty}{dose_unit}")

    # Route
    if route:
        snomed = _ROUTE_SNOMED.get(route)
        if snomed:
            dosage["route"] = {
                "coding": [{"system": "http://snomed.info/sct", **snomed}],
                "text": route,
            }
        else:
            dosage["route"] = {"text": route}
        parts.append(route)

    # Timing
    if freq_per_day:
        dosage["timing"] = {
            "repeat": {
                "frequency": freq_per_day,
                "period": 1,
                "periodUnit": "d",
            },
        }
        parts.append(freq or f"{freq_per_day}x/day")
    elif freq:
        parts.append(freq)

    # Text summary
    if parts:
        if country == "JP":
            ja_parts = []
            for p in parts:
                p_upper = p.upper()
                ja_parts.append(_ROUTE_JA.get(p_upper) or _FREQ_JA.get(p_upper) or _FREQ_JA.get(p) or p)
            dosage["text"] = " ".join(ja_parts)
        else:
            dosage["text"] = " ".join(parts)
    elif order.get("display_name"):
        dosage["text"] = order["display_name"]

    return dosage if dosage else None


def _build_medication_request(
    order: dict, patient_id: str, country: str,
    encounter_id: str = "", primary_dx_code: str = "",
) -> dict:
    """Build FHIR MedicationRequest resource."""
    drug_name_raw = order.get("display_name", "Unknown medication")
    drug_name = _localize_drug_name(drug_name_raw, country)
    # Strip dose info to get base drug name for code lookup
    base_name = drug_name_raw.split(" ")[0] if drug_name_raw else ""

    country_code = "JP" if country != "US" else "US"
    lang = "ja" if country_code == "JP" else "en"
    drug_codes = load_code_mapping("drug", country_code)  # name → RxNorm/YJ

    code_value = drug_codes.get(base_name, "")
    drug_system_key = "yj" if country_code == "JP" else "rxnorm"
    display = code_lookup(drug_system_key, code_value, lang) if code_value else drug_name
    if display == code_value:
        display = drug_name
    code_system = get_system_uri(drug_system_key)

    med_concept: dict[str, Any] = {"text": drug_name}
    if code_value:
        med_concept["coding"] = [{
            "system": code_system,
            "code": code_value,
            "display": display,
        }]

    # ID: prepend encounter_id to ensure global uniqueness across patient's
    # multiple encounters (raw order_id is patient-scoped only)
    base_oid = order.get("order_id") or str(uuid.uuid4())
    enc_ref_id = order.get("encounter_id", "") or encounter_id
    resource_id = f"{enc_ref_id}-{base_oid}" if enc_ref_id else base_oid

    resource: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": resource_id,
        "status": "active" if order.get("status") != "cancelled" else "cancelled",
        "intent": "order",
        "medicationCodeableConcept": med_concept,
        "subject": {"reference": f"Patient/{patient_id}"},
        "authoredOn": order.get("ordered_datetime", ""),
    }

    # Encounter reference
    enc_ref = order.get("encounter_id", "") or encounter_id
    if enc_ref:
        resource["encounter"] = {"reference": f"Encounter/{enc_ref}"}

    # Requester (ordering physician)
    if order.get("ordered_by"):
        resource["requester"] = {"reference": f"Practitioner/{order['ordered_by']}"}

    # Dosage instruction
    dosage = _build_dosage_instruction(order, country=country)
    if dosage:
        resource["dosageInstruction"] = [dosage]

    # Reason reference (link to primary diagnosis Condition)
    reason = order.get("reason_condition", "") or primary_dx_code
    if reason:
        cond_ref = f"cond-{encounter_id}-primary" if encounter_id else f"cond-{patient_id}-primary"
        resource["reasonReference"] = [{
            "reference": f"Condition/{cond_ref}",
        }]

    return resource


def _build_medication_admin(
    mar: dict, patient_id: str, index: int, country: str = "US",
    encounter_id: str = "", primary_dx_code: str = "",
) -> dict:
    """Build FHIR MedicationAdministration resource."""
    drug_name_raw = mar.get("drug_name", "")
    drug_name = _localize_drug_name(drug_name_raw, country)
    base_name = drug_name_raw.split(" ")[0] if drug_name_raw else ""
    country_code = "JP" if country != "US" else "US"
    lang = "ja" if country_code == "JP" else "en"
    drug_codes = load_code_mapping("drug", country_code)
    code_value = drug_codes.get(base_name, "")
    drug_system_key = "yj" if country_code == "JP" else "rxnorm"
    code_system = get_system_uri(drug_system_key)

    med_concept: dict[str, Any] = {"text": drug_name}
    if code_value:
        display = code_lookup(drug_system_key, code_value, lang)
        coding = {"system": code_system, "code": code_value}
        if display and display != code_value:
            coding["display"] = display
        med_concept["coding"] = [coding]

    resource: dict[str, Any] = {
        "resourceType": "MedicationAdministration",
        "id": f"mar-{encounter_id or patient_id}-{index:05d}",
        "status": _map_mar_status(mar.get("status", "completed")),
        "medicationCodeableConcept": med_concept,
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": mar.get("actual_datetime") or mar.get("scheduled_datetime", ""),
    }

    # Encounter context
    if encounter_id:
        resource["context"] = {"reference": f"Encounter/{encounter_id}"}

    if mar.get("administered_by"):
        resource["performer"] = [{"actor": {"reference": f"Practitioner/{mar['administered_by']}"}}]

    # Dosage with structured dose + route
    dose_text = mar.get("dose", "") or drug_name
    dose_str = mar.get("dose", "")
    parsed = _parse_dose_for_mar(dose_str or drug_name)
    dosage: dict[str, Any] = {"text": dose_text}
    if parsed.get("dose_quantity") is not None and parsed.get("dose_unit"):
        dosage["dose"] = {
            "value": parsed["dose_quantity"],
            "unit": parsed["dose_unit"],
            "system": "http://unitsofmeasure.org",
        }
    # Rate for continuous infusions
    if "CONTINUOUS" in dose_text.upper() or "DRIP" in dose_text.upper() or "/h" in dose_text:
        dosage["rateQuantity"] = {
            "value": parsed.get("dose_quantity") or 1,
            "unit": (parsed.get("dose_unit", "mL") + "/h"),
            "system": "http://unitsofmeasure.org",
        }
    # Route
    route = (mar.get("route") or parsed.get("route") or "").upper()
    if route:
        snomed = _ROUTE_SNOMED.get(route)
        if snomed:
            dosage["route"] = {
                "coding": [{"system": "http://snomed.info/sct", **snomed}],
                "text": route,
            }
        else:
            dosage["route"] = {"text": route}
    resource["dosage"] = dosage

    # Reason reference (link to primary diagnosis)
    if primary_dx_code:
        cond_ref = f"cond-{encounter_id}-primary" if encounter_id else f"cond-{patient_id}-primary"
        resource["reasonReference"] = [{
            "reference": f"Condition/{cond_ref}",
        }]

    return resource


def _parse_dose_for_mar(text: str) -> dict[str, Any]:
    """Lightweight dose parser for MAR (avoids importing order engine in adapter)."""
    import re
    result: dict[str, Any] = {}
    if not text:
        return result
    m = re.search(r"(\d+(?:\.\d+)?)\s*(mg|g|mcg|ug|mL|ml|L|IU|U|unit|units|%)",
                  text, re.IGNORECASE)
    if m:
        try:
            result["dose_quantity"] = float(m.group(1))
            result["dose_unit"] = m.group(2)
        except ValueError:
            pass
    route_match = re.search(r"\b(PO|IV|SC|IM|SL|PR|NG|inhaled|topical)\b", text, re.IGNORECASE)
    if route_match:
        result["route"] = route_match.group(1).upper()
    return result


def _build_procedure(proc: dict, patient_id: str, index: int, country: str) -> dict:
    """Build FHIR Procedure resource."""
    code_system_key = "k-codes" if country == "JP" else "cpt"
    code_system = get_system_uri(code_system_key)
    sct_uri = get_system_uri("snomed-ct")
    lang = "ja" if country == "JP" else "en"

    # Use performedDateTime for point-in-time procedures, performedPeriod for longer ones
    start = proc.get("start_datetime", "")
    end = proc.get("end_datetime", "")

    # Encounter-scoped id to avoid collisions across patient's multiple encounters
    enc_id = proc.get("encounter_id", "")
    base_pid = proc.get("procedure_id") or f"proc-{patient_id}-{index:03d}"
    resource_id = f"{enc_id}-{base_pid}" if enc_id else base_pid

    resource: dict[str, Any] = {
        "resourceType": "Procedure",
        "id": resource_id,
        "status": "completed",
        "code": {
            "coding": [{"system": code_system, "code": proc.get("procedure_code", ""), "display": proc.get("procedure_name", "")}],
            "text": proc.get("procedure_name", ""),
        },
        "subject": {"reference": f"Patient/{patient_id}"},
    }

    # category (SNOMED)
    category_code = proc.get("category_code", "")
    if category_code:
        resource["category"] = {
            "coding": [{
                "system": sct_uri,
                "code": category_code,
                "display": code_lookup("snomed-ct", category_code, lang),
            }],
        }

    if start and end and start != end:
        resource["performedPeriod"] = {"start": start, "end": end}
    elif start:
        resource["performedDateTime"] = start

    if proc.get("encounter_id"):
        resource["encounter"] = {"reference": f"Encounter/{proc['encounter_id']}"}

    # performer[] with function (surgeon, anesthesiologist)
    performers: list[dict[str, Any]] = []
    surgeon_id = proc.get("primary_surgeon_id", "")
    anes_id = proc.get("anesthesiologist_id", "")
    if surgeon_id:
        performers.append({
            "function": {
                "coding": [{
                    "system": sct_uri,
                    "code": "304292004",
                    "display": code_lookup("snomed-ct", "304292004", lang),
                }],
            },
            "actor": {"reference": f"Practitioner/{surgeon_id}"},
        })
    if anes_id and anes_id != surgeon_id:
        performers.append({
            "function": {
                "coding": [{
                    "system": sct_uri,
                    "code": "158967008",
                    "display": code_lookup("snomed-ct", "158967008", lang),
                }],
            },
            "actor": {"reference": f"Practitioner/{anes_id}"},
        })
    if performers:
        resource["performer"] = performers
        # recorder (default to surgeon when available)
        resource["recorder"] = {"reference": f"Practitioner/{surgeon_id or anes_id}"}

    # reasonReference — link to encounter's primary Condition
    if enc_id:
        resource["reasonReference"] = [
            {"reference": f"Condition/cond-{enc_id}-primary"}
        ]

    # bodySite (SNOMED)
    body_site_code = proc.get("body_site_code", "")
    if body_site_code:
        resource["bodySite"] = [{
            "coding": [{
                "system": sct_uri,
                "code": body_site_code,
                "display": code_lookup("snomed-ct", body_site_code, lang),
            }],
        }]

    # location (OR etc.)
    location_id = proc.get("location_id", "")
    if location_id:
        resource["location"] = {"reference": f"Location/{location_id}"}

    # outcome (SNOMED)
    outcome_code = proc.get("outcome_code", "")
    if outcome_code:
        resource["outcome"] = {
            "coding": [{
                "system": sct_uri,
                "code": outcome_code,
                "display": code_lookup("snomed-ct", outcome_code, lang),
            }],
        }

    # complication (SNOMED)
    comp_codes = proc.get("complication_codes", []) or []
    if comp_codes:
        resource["complication"] = [
            {
                "coding": [{
                    "system": sct_uri,
                    "code": c,
                    "display": code_lookup("snomed-ct", c, lang),
                }],
            }
            for c in comp_codes
        ]

    return resource


def _build_document_reference(
    doc: dict[str, Any],
    patient_id: str,
    country: str,
) -> dict[str, Any] | None:
    """Build a FHIR R4 DocumentReference resource from a narrative CIF document.

    The narrative CIF format is defined by ClinicalDocument in
    clinosim/types/clinical.py and written by document_generator.py.
    """
    import base64

    text = doc.get("text", "") or ""
    if not text:
        # Empty stubs (Stage 1 only, no Stage 2 run) are not emitted —
        # per FHIR R4 spec, DocumentReference requires at least one
        # content.attachment, and an empty attachment would be useless
        # to downstream consumers.
        return None

    loinc_code = doc.get("loinc_code", "")
    if not loinc_code:
        return None
    lang = doc.get("language") or ("ja" if country == "JP" else "en")
    type_display = code_lookup("loinc", loinc_code, lang) or loinc_code

    # DocumentReference.id must be unique; ClinicalDocument.document_id
    # already follows doc-<encounter_id>-<task_type>[-suffix]
    resource_id = doc.get("document_id") or (
        f"doc-{doc.get('encounter_id','unknown')}-{doc.get('task_type','note')}"
    )

    # base64 encode the content
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")

    resource: dict[str, Any] = {
        "resourceType": "DocumentReference",
        "id": resource_id,
        "status": "current",
        "docStatus": "final" if doc.get("text_source") != "template" else "preliminary",
        "type": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": loinc_code,
                    "display": type_display,
                }
            ],
            "text": type_display,
        },
        "category": [
            {
                "coding": [
                    {
                        "system": "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
                        "code": "clinical-note",
                        "display": "Clinical Note",
                    }
                ]
            }
        ],
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": doc.get("authored_datetime", "") or doc.get("generated_at", ""),
        "content": [
            {
                "attachment": {
                    "contentType": doc.get(
                        "content_type", "text/plain; charset=utf-8"
                    ),
                    "language": lang,
                    "data": encoded,
                    "title": type_display,
                    "size": len(text.encode("utf-8")),
                    "hash": _sha1_b64(text),
                }
            }
        ],
    }

    # Author (Practitioner reference)
    author_id = doc.get("author_practitioner_id", "")
    if author_id:
        resource["author"] = [{"reference": f"Practitioner/{author_id}"}]

    # Encounter context
    enc_id = doc.get("encounter_id", "")
    if enc_id:
        context: dict[str, Any] = {"encounter": [{"reference": f"Encounter/{enc_id}"}]}
        period_start = doc.get("period_start", "")
        period_end = doc.get("period_end", "")
        if period_start and period_end:
            context["period"] = {"start": period_start, "end": period_end}
        elif period_start:
            context["period"] = {"start": period_start}

        # Related procedure (for operative / procedure notes).
        # Procedure.id in the FHIR export is encounter-scoped: "<enc_id>-<base_procedure_id>"
        # (see _build_procedure). Apply the same scoping here so the reference resolves.
        related_proc = doc.get("related_procedure_id", "")
        if related_proc:
            scoped_proc_id = (
                f"{enc_id}-{related_proc}" if enc_id and not related_proc.startswith(enc_id)
                else related_proc
            )
            context["related"] = [
                {"reference": f"Procedure/{scoped_proc_id}"}
            ]
        resource["context"] = context

    return resource


def _sha1_b64(text: str) -> str:
    """Return base64-encoded SHA1 hash of text, as required by FHIR Attachment.hash."""
    import base64
    import hashlib
    h = hashlib.sha1(text.encode("utf-8")).digest()
    return base64.b64encode(h).decode("ascii")


_ROLE_PREFIX_MAP: dict[str, dict[str, str]] = {
    "physician": {"qual_code": "MD", "qual_display": "Doctor of Medicine"},
    "nurse": {"qual_code": "RN", "qual_display": "Registered Nurse"},
    "lab_technician": {"qual_code": "MT", "qual_display": "Medical Technologist"},
    "radiologist": {"qual_code": "MD", "qual_display": "Doctor of Medicine"},
    "pharmacist": {"qual_code": "PharmD", "qual_display": "Doctor of Pharmacy"},
}
_ROLE_PREFIX_MAP_JA: dict[str, dict[str, str]] = {
    "physician": {"qual_code": "MD", "qual_display": "医師", "prefix": ""},
    "nurse": {"qual_code": "RN", "qual_display": "看護師", "prefix": ""},
    "lab_technician": {"qual_code": "MT", "qual_display": "臨床検査技師", "prefix": ""},
    "radiologist": {"qual_code": "MD", "qual_display": "放射線科医", "prefix": ""},
    "pharmacist": {"qual_code": "PharmD", "qual_display": "薬剤師", "prefix": ""},
}

# SNOMED specialty codes
_SPECIALTY_SNOMED: dict[str, dict[str, str]] = {
    "general": {"code": "419192003", "display": "Internal Medicine"},
    "cardiology": {"code": "394579002", "display": "Cardiology"},
    "pulmonology": {"code": "418112009", "display": "Pulmonary medicine"},
    "gastro": {"code": "394584008", "display": "Gastroenterology"},
    "nephro": {"code": "394589003", "display": "Nephrology"},
    "endo": {"code": "394583003", "display": "Endocrinology"},
    "internal_medicine": {"code": "419192003", "display": "Internal Medicine"},
    "radiology": {"code": "394914008", "display": "Radiology"},
    "laboratory": {"code": "722414000", "display": "Laboratory medicine"},
    "pharmacy": {"code": "405623001", "display": "Pharmacy"},
}


def _build_practitioner(staff_id: str, roster_map: dict[str, dict] | None = None, country: str = "US") -> dict:
    """Build FHIR Practitioner resource. Uses roster data when available."""
    resource: dict[str, Any] = {
        "resourceType": "Practitioner",
        "id": staff_id,
        "active": True,
        "identifier": [{"system": "urn:clinosim:staff", "value": staff_id}],
    }

    staff = (roster_map or {}).get(staff_id)
    if staff:
        full_name = staff.get("name", "")
        role = staff.get("role", "")

        # Parse name (JP: "姓 名", US: "given family")
        parts = full_name.split(" ", 1)
        if len(parts) == 2:
            # Determine ordering by checking for non-ASCII
            if any(ord(c) > 0x3000 for c in full_name):
                family, given = parts[0], parts[1]
            else:
                given, family = parts[0], parts[1]
        else:
            family, given = full_name, ""

        name_obj: dict[str, Any] = {"family": family, "given": [given] if given else []}
        if role in ("physician", "radiologist") and country != "JP":
            name_obj["prefix"] = ["Dr."]
        resource["name"] = [name_obj]

        # Gender
        sex = staff.get("sex", "")
        if sex == "M":
            resource["gender"] = "male"
        elif sex == "F":
            resource["gender"] = "female"

        # Telecom
        telecoms = []
        if staff.get("phone"):
            telecoms.append({"system": "phone", "value": staff["phone"], "use": "work"})
        if staff.get("email"):
            telecoms.append({"system": "email", "value": staff["email"], "use": "work"})
        if telecoms:
            resource["telecom"] = telecoms

        # Qualification
        qual = (_ROLE_PREFIX_MAP_JA if country == "JP" else _ROLE_PREFIX_MAP).get(role)
        if qual:
            qualification: dict[str, Any] = {
                "code": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0360",
                        "code": qual["qual_code"],
                        "display": qual["qual_display"],
                    }],
                },
            }
            qual_year = staff.get("qualification_year")
            if qual_year:
                qualification["period"] = {"start": f"{qual_year}-01-01"}
            resource["qualification"] = [qualification]

    return resource


def _build_practitioner_role(staff_id: str, roster_map: dict[str, dict] | None = None) -> dict | None:
    """Build FHIR PractitionerRole resource (specialty + department)."""
    staff = (roster_map or {}).get(staff_id)
    if not staff:
        return None

    role = staff.get("role", "")
    department = staff.get("department", "")
    specialty = staff.get("specialty", "") or department

    role_code_map = {
        "physician": "doctor",
        "radiologist": "doctor",
        "nurse": "nurse",
        "lab_technician": "ict",
        "pharmacist": "pharmacist",
    }
    role_code = role_code_map.get(role, "")

    spec_info = _SPECIALTY_SNOMED.get(specialty) or _SPECIALTY_SNOMED.get(department)

    resource: dict[str, Any] = {
        "resourceType": "PractitionerRole",
        "id": f"role-{staff_id}",
        "active": True,
        "practitioner": {"reference": f"Practitioner/{staff_id}"},
    }

    # Organization (department) reference
    if department and department not in ("laboratory", "radiology", "pharmacy"):
        resource["organization"] = {
            "reference": f"Organization/dept-{department.replace('_', '-')}",
        }

    # Location reference (for nurses assigned to a ward)
    ward = staff.get("ward", "")
    if ward:
        resource["location"] = [{
            "reference": f"Location/loc-ward-{ward}",
        }]

    if role_code:
        resource["code"] = [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/practitioner-role",
                "code": role_code,
            }],
        }]

    if spec_info:
        resource["specialty"] = [{
            "coding": [{
                "system": "http://snomed.info/sct",
                **spec_info,
            }],
            "text": spec_info["display"],
        }]

    return resource


def _build_reference_range(
    lab_name: str, patient_sex: str, country_code: str,
) -> list[dict[str, Any]] | None:
    """Build FHIR referenceRange from locale reference range data.

    For JP: uses JCCLS共用基準範囲 2022 with source extension.
    Sex-specific ranges are filtered by patient sex with appliesTo.
    """
    ref_data = load_reference_ranges(country_code)
    if not ref_data:
        return None

    ranges = ref_data.get("ranges", {}).get(lab_name)
    if not ranges:
        return None

    source_url = ref_data.get("source_url", "")
    result: list[dict[str, Any]] = []

    for entry in ranges:
        sex = entry.get("sex")
        # If sex-specific, only include the matching range (or both if sex unknown)
        if sex and patient_sex and sex != patient_sex:
            continue

        rr: dict[str, Any] = {}
        unit_str = entry.get("unit", "")
        if entry.get("low") is not None:
            rr["low"] = {
                "value": entry["low"], "unit": unit_str,
                "system": "http://unitsofmeasure.org", "code": unit_str,
            }
        if entry.get("high") is not None:
            rr["high"] = {
                "value": entry["high"], "unit": unit_str,
                "system": "http://unitsofmeasure.org", "code": unit_str,
            }
        if entry.get("text"):
            rr["text"] = entry["text"]

        # appliesTo for sex-specific ranges
        if sex:
            rr["appliesTo"] = [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/v3-AdministrativeGender",
                    "code": sex,
                }],
            }]

        # Source extension (JP Core)
        if source_url:
            rr["extension"] = [{
                "url": "http://jpfhir.jp/fhir/core/StructureDefinition/"
                       "JP_Observation_Common#referenceRangeSource",
                "valueString": source_url,
            }]

        result.append(rr)

    return result if result else None


def _map_mar_status(status: str) -> str:
    return {"given": "completed", "held": "on-hold", "refused": "not-done", "not_available": "not-done"}.get(status, "completed")


def _map_encounter_status(status: str) -> str:
    mapping = {
        "planned": "planned",
        "in_progress": "in-progress",
        "completed": "finished",
        "cancelled": "cancelled",
    }
    return mapping.get(status, "unknown")
