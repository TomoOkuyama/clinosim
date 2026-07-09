"""FHIR R4 Practitioner / PractitionerRole resource builders (FA-1 Phase 4).

Extracted verbatim from ``fhir_r4_adapter``. Both builders are self-contained:
they depend only on :mod:`clinosim.codes` and the leaf reference/localization
modules, so they import no helpers back through the adapter facade.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output._fhir_common import _coding_with_display
from clinosim.modules.output._fhir_localization import _ROLE_PREFIX_MAP_JA
from clinosim.modules.output._fhir_reference_data import (
    _ROLE_PREFIX_MAP,
    _SPECIALTY_SNOMED,
)


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
        if role in ("physician", "radiologist") and not is_jp(country):
            name_obj["prefix"] = ["Dr."]
        # C3-01 (session 42 cycle 3): JP Core requires kanji (IDE)
        # representation tag on Practitioner names as well as Patient.
        # C2-19 continuation (session 43 cycle 5): Kana SYL entry now
        # emitted when roster generation populated `name_phonetic`.
        # names.yaml carries kana column for every kanji entry so JP
        # rosters always fill this field.
        names_list: list[dict[str, Any]] = []
        if is_jp(country):
            names_list.append({
                **name_obj,
                "use": "official",
                "extension": [{
                    "url": "http://hl7.org/fhir/StructureDefinition/iso21090-EN-representation",
                    "valueCode": "IDE",
                }],
            })
            phonetic = staff.get("name_phonetic", "")
            if phonetic:
                p_parts = phonetic.split(" ", 1)
                if len(p_parts) == 2:
                    p_family, p_given = p_parts[0], p_parts[1]
                else:
                    p_family, p_given = phonetic, ""
                names_list.append({
                    "use": "official",
                    "family": p_family,
                    "given": [p_given] if p_given else [],
                    "extension": [{
                        "url": "http://hl7.org/fhir/StructureDefinition/iso21090-EN-representation",
                        "valueCode": "SYL",
                    }],
                })
        else:
            names_list.append(name_obj)
        resource["name"] = names_list

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
        qual = (_ROLE_PREFIX_MAP_JA if is_jp(country) else _ROLE_PREFIX_MAP).get(role)
        if qual:
            qualification: dict[str, Any] = {
                "code": {
                    "coding": [{
                        "system": get_system_uri("hl7-v2-0360"),
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


def _build_practitioner_role(
    staff_id: str,
    roster_map: dict[str, dict] | None = None,
    country: str = "US",
) -> dict | None:
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
        # C2-07 (session 42 cycle 2): resolve display via codes/data/
        # hl7-practitioner-role.yaml — was raw code with no display.
        resource["code"] = [{
            "coding": [_coding_with_display(
                "hl7-practitioner-role", role_code, resolve_lang(country),
            )],
        }]

    if spec_info:
        # C5-05 (session 43 cycle 5): resolve specialty display through
        # snomed-ct.yaml so JP output uses 内科/循環器内科 etc. instead of
        # the English fallback baked into _SPECIALTY_SNOMED entries.
        _lang = resolve_lang(country)
        _snomed_code = spec_info["code"]
        _spec_display = code_lookup("snomed-ct", _snomed_code, _lang) or spec_info["display"]
        resource["specialty"] = [{
            "coding": [{
                "system": get_system_uri("snomed-ct"),
                "code": _snomed_code,
                "display": _spec_display,
            }],
            "text": _spec_display,
        }]

    return resource
