"""FHIR R4 Practitioner / PractitionerRole resource builders (FA-1 Phase 4).

Extracted verbatim from ``fhir_r4_adapter``. Both builders are self-contained:
they depend only on :mod:`clinosim.codes` and the leaf reference/localization
modules, so they import no helpers back through the adapter facade.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
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
        resource["specialty"] = [{
            "coding": [{
                "system": get_system_uri("snomed-ct"),
                **spec_info,
            }],
            "text": spec_info["display"],
        }]

    return resource
