"""FHIR R4 facility master bundle builder (Organization + Location) (FA-1 facility).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

from datetime import datetime

from clinosim.codes import get_system_uri
from clinosim.modules.output._fhir_common import _entry
from clinosim.modules.output._fhir_localization import (
    _LOCATION_NAME_JA,
    _LOCATION_TYPE_DISPLAY_JA,
    _ORG_TYPE_DISPLAY_JA,
    _dept_display,
    _localize_display,
)


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
                "system": get_system_uri("hl7-organization-type"),
                "code": "prov",
                "display": _localize_display("Healthcare Provider", country, _ORG_TYPE_DISPLAY_JA),
            }],
        }],
        "name": hosp_name,
        "alias": [f"{beds}-bed hospital"] if beds else [],
    }
    entries.append(_entry(root_org))

    # Department Organizations (one per available_department)
    for dept in available:
        display = _dept_display(dept, country)
        dept_org = {
            "resourceType": "Organization",
            "id": f"dept-{dept.replace('_', '-')}",
            "active": True,
            "type": [{
                "coding": [{
                    "system": get_system_uri("hl7-organization-type"),
                    "code": "dept",
                    "display": _localize_display("Hospital Department", country, _ORG_TYPE_DISPLAY_JA),
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
                "name": (f"{ward}病棟" if country == "JP" else f"Ward {ward}") if ward not in ("ER", "OPD") else _localize_display(phys_display, country, _LOCATION_NAME_JA),
                "physicalType": {
                    "coding": [{
                        "system": get_system_uri("hl7-location-physical-type"),
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
                                "system": get_system_uri("hl7-location-physical-type"),
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
                        "system": get_system_uri("hl7-location-physical-type"),
                        "code": "ro",
                        "display": "Room",
                    }],
                },
                "type": [{
                    "coding": [{
                        "system": get_system_uri("hl7-v3-rolecode"),
                        "code": "OR",
                        "display": _localize_display("Operating Room", country, _LOCATION_TYPE_DISPLAY_JA),
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
