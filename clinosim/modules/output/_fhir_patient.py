"""FHIR R4 patient-demographics resource builders (FA-1 Phase 11).

Patient, JP Core Coverage (+ payor Organization), occupation Observation, and
AllergyIntolerance — plus the identity-config cache and the marital/language/
coverage display constants used only by this cluster. Extracted verbatim from
``fhir_r4_adapter``; depends only on clinosim.codes/locale and the leaf
reference/localization + _fhir_common helper modules (no adapter import cycle).
"""

from __future__ import annotations

import uuid
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_identity_config
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output._fhir_common import _build_address, _build_telecom
from clinosim.modules.output._fhir_localization import (
    _CATEGORY_DISPLAY_JA,
    _OCCUPATION_DISPLAY_EN,
    _OCCUPATION_DISPLAY_JA,
    _RELATIONSHIP_DISPLAY_JA,
    _localize_display,
    _localize_drug_name,
)
from clinosim.modules.output._fhir_reference_data import _ALLERGEN_RXNORM

_IDENTITY_CFG_CACHE: dict[str, dict] = {}

# FHIR R4 standard: payer organization type
_ORG_TYPE_SYSTEM = get_system_uri("hl7-organization-type")
# FHIR R4 standard: beneficiary's relationship to the policy subscriber
_SUBSCRIBER_REL_SYSTEM = get_system_uri("hl7-subscriber-relationship")


def _identity_cfg(country: str) -> dict:
    """Full resident-identity locale config (AD-54), cached."""
    if country not in _IDENTITY_CFG_CACHE:
        _IDENTITY_CFG_CACHE[country] = load_identity_config(country)
    return _IDENTITY_CFG_CACHE[country]


def _payer_name_map(country: str) -> dict[str, str]:
    """Map 保険者番号 → insurer name from locale (display resolved at output, AD-30)."""
    payers = _identity_cfg(country).get("payers", {})
    out: dict[str, str] = {}
    for entries in payers.values():
        for e in entries or []:
            if e.get("number"):
                out[str(e["number"])] = str(e.get("name", e["number"]))
    return out


def _build_coverage_resources(patient_data: dict, country: str) -> list[dict]:
    """Build JP Core Coverage + payor Organization from the patient's insurance enrollment.

    Reads CIF data only (no dependency on the identity module — module independence).
    `national_id` is never read here: the privacy chokepoint (AD-54) means individual
    numbers are never emitted to FHIR.
    """
    cfg = _identity_cfg(country).get("fhir_coverage", {})
    if not cfg:
        return []
    name_map = _payer_name_map(country)
    type_labels = _identity_cfg(country).get("coverage_type_labels", {})
    identity = patient_data.get("identity") or {}
    enrollments = identity.get("enrollments") or []
    pid = patient_data.get("patient_id", "")
    resources: list[dict] = []

    for idx, enr in enumerate(enrollments):
        insurer = enr.get("insurer_number") or ""
        number = enr.get("member_id") or ""
        symbol = enr.get("group_symbol")
        branch = enr.get("branch_number")
        category = enr.get("category") or ""
        if not insurer or not number:
            continue

        payer_org_id = f"payer-{insurer}"
        resources.append({
            "resourceType": "Organization",
            "id": payer_org_id,
            "identifier": [{
                "system": cfg.get("insurer_number_system", ""),
                "value": insurer,
            }],
            "type": [{"coding": [{
                "system": _ORG_TYPE_SYSTEM,
                "code": "pay",
                "display": "Payer",
            }]}],
            "name": name_map.get(insurer, insurer),
        })

        # JP Core extensions: 記号 / 番号 / 枝番
        extensions: list[dict] = []
        if symbol:
            extensions.append({"url": cfg.get("ext_symbol", ""), "valueString": symbol})
        extensions.append({"url": cfg.get("ext_number", ""), "valueString": number})
        if branch:
            extensions.append({"url": cfg.get("ext_subnumber", ""), "valueString": branch})

        # Composite member identifier: 保険者番号:記号:番号:枝番
        composite = ":".join([insurer, symbol or "", number, branch or ""])
        subscriber = f"{symbol}:{number}" if symbol else number

        coverage: dict[str, Any] = {
            "resourceType": "Coverage",
            "id": f"cov-{pid}-{idx}",
            "extension": extensions,
            "identifier": [{"system": cfg.get("member_id_system", ""), "value": composite}],
            "status": "active",
            "subscriberId": subscriber,
            "beneficiary": {"reference": f"Patient/{pid}"},
            "payor": [{"reference": f"Organization/{payer_org_id}"}],
        }
        if cfg.get("profile"):
            coverage["meta"] = {"profile": [cfg["profile"]]}
        if branch:
            coverage["dependent"] = branch
        # Beneficiary's relationship to the subscriber: 被扶養者 → not self.
        rel_code = "other" if category == "dependent" else "self"
        coverage["relationship"] = {
            "coding": [{"system": _SUBSCRIBER_REL_SYSTEM, "code": rel_code}]
        }
        # Coverage.type: human label (text-only CodeableConcept — no fabricated codes).
        label = type_labels.get(category)
        if label:
            coverage["type"] = {"text": label}
        period = {}
        if enr.get("valid_from"):
            period["start"] = enr["valid_from"]
        if enr.get("valid_to"):
            period["end"] = enr["valid_to"]
        if period:
            coverage["period"] = period
        resources.append(coverage)

    return resources


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
    if phonetic and is_jp(country):
        # JP: add phonetic representation (katakana)
        fhir_name["extension"] = [{
            "url": "http://hl7.org/fhir/StructureDefinition/iso21090-EN-representation",
            "valueString": "SYL",
        }]

    pid = p.get("patient_id", str(uuid.uuid4()))
    # Hospital MRN identifier system (country-specific)
    mrn_system = (
        "urn:oid:1.2.392.100495.20.3.51.1"  # JP example MRN OID
        if is_jp(country)
        else "http://hospital.example.org/identifiers/mrn"
    )
    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": pid,
        "identifier": [{
            "use": "usual",
            "type": {
                "coding": [{
                    "system": get_system_uri("hl7-v2-0203"),
                    "code": "MR",
                    "display": "Medical Record Number",
                }],
                "text": "診療録番号" if is_jp(country) else "MRN",
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
                "system": get_system_uri("hl7-v3-maritalstatus"),
                "code": marital,
                "display": code_lookup("hl7-v3-maritalstatus", marital, resolve_lang(country)),
            }],
        }

    # Communication / preferred language
    lang = p.get("preferred_language", "")
    if lang:
        resource["communication"] = [{
            "language": {
                "coding": [{
                    "system": get_system_uri("bcp-47-language"),
                    "code": lang,
                    "display": code_lookup("bcp-47-language", lang, resolve_lang(country)),
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
                        "system": get_system_uri("hl7-v2-0131"),
                        "code": "C",
                        "display": "Emergency Contact",
                    }],
                    "text": _localize_display(emer_rel, country, _RELATIONSHIP_DISPLAY_JA),
                }]
            if emer_name:
                ec["name"] = {"text": emer_name}
            if emer_phone:
                ec["telecom"] = [{
                    "system": "phone", "value": emer_phone, "use": "mobile",
                }]
            resource["contact"] = [ec]

    return resource


# ============================================================
# AllergyIntolerance
# ============================================================


# Occupation category localization for Observation.valueCodeableConcept
def _build_occupation_observation(
    occupation: str, patient_id: str, country: str,
) -> dict | None:
    """Build FHIR Observation for patient occupation (social history).

    Uses US Core Patient Occupation profile (LOINC 11341-5).
    Reference: http://hl7.org/fhir/us/core/StructureDefinition/us-core-occupation
    """
    if not occupation:
        return None
    display_map = _OCCUPATION_DISPLAY_JA if is_jp(country) else _OCCUPATION_DISPLAY_EN
    display = display_map.get(occupation, occupation.title())
    category_text = "社会歴" if is_jp(country) else "Social History"
    return {
        "resourceType": "Observation",
        "id": f"occupation-{patient_id}",
        "status": "final",
        "category": [{
            "coding": [{
                "system": get_system_uri("hl7-observation-category"),
                "code": "social-history",
                "display": _localize_display("Social History", country, _CATEGORY_DISPLAY_JA),
            }],
            "text": category_text,
        }],
        "code": {
            "coding": [{
                "system": get_system_uri("loinc"),
                "code": "11341-5",
                "display": "History of Occupation",
            }],
            "text": "職業" if is_jp(country) else "Occupation",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "valueCodeableConcept": {
            "coding": [{
                "system": get_system_uri("occupation-category"),
                "code": occupation,
                "display": display,
            }],
            "text": display,
        },
    }


def _build_allergy_intolerance(
    allergy: dict, patient_id: str, index: int, country: str,
) -> dict | None:
    """Build FHIR AllergyIntolerance from CIF allergy data."""
    substance = allergy.get("substance", "")
    if not substance:
        return None

    # Localize substance display for JP
    substance_display = _localize_drug_name(substance, country) if is_jp(country) else substance

    rxnorm = _ALLERGEN_RXNORM.get(substance, "")
    code: dict[str, Any] = {"text": substance_display}
    if rxnorm:
        code["coding"] = [{
            "system": get_system_uri("rxnorm"),
            "code": rxnorm,
            "display": substance_display,
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
                "system": get_system_uri("hl7-allergyintolerance-clinical"),
                "code": "active",
                "display": "Active",
            }],
        },
        "verificationStatus": {
            "coding": [{
                "system": get_system_uri("hl7-allergyintolerance-verification"),
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
