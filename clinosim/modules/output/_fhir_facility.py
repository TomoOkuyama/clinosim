"""FHIR R4 facility master bundle builder (Organization + Location) (FA-1 facility).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

from clinosim.codes import get_system_uri
from clinosim.modules._shared import is_jp
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
    # C3-17 (session 42 cycle 3): JP Core Organization profile also on
    # facility-bundle entries (adapter's post-hook doesn't touch the
    # separate facility bundle).
    _jp_org_profile = (
        {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Organization"]}}
        if is_jp(country)
        else {}
    )
    hosp_name = "総合病院" if is_jp(country) else "Community Hospital"
    root_org = {
        "resourceType": "Organization",
        "id": "hospital-main",
        **_jp_org_profile,
        "active": True,
        "type": [
            {
                "coding": [
                    {
                        "system": get_system_uri("hl7-organization-type"),
                        "code": "prov",
                        "display": _localize_display("Healthcare Provider", country, _ORG_TYPE_DISPLAY_JA),
                    }
                ],
            }
        ],
        "name": hosp_name,
        "alias": [f"{beds}-bed hospital"] if beds else [],
    }
    entries.append(_entry(root_org))

    # Session 61 #313: Emit eCS-compliant Organization for eReferral 920/910
    # section entry slices (referralFromOrganization / referralToOrganization).
    # hospital-main uses JP Core profile, which fails the eCS slice discriminator
    # (type: profile, path: resolve()). eCS profile requires 8 fields min=1.
    root_org_ecs = {
        "resourceType": "Organization",
        "id": "hospital-main-ecs",
        **(
            {
                "meta": {
                    "profile": ["http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Organization_eCS"],
                    "lastUpdated": "2024-01-01T12:00:00Z"
                }
            }
            if is_jp(country)
            else {}
        ),
        "identifier": [
            {
                "system": "http://jpfhir.jp/fhir/core/IdSystem/insurance-medical-institution-no",
                "value": "1311234567"  # placeholder
            }
        ],
        "active": True,
        "type": [
            {
                "coding": [
                    {
                        "system": get_system_uri("hl7-organization-type"),
                        "code": "prov",
                        "display": _localize_display("Healthcare Provider", country, _ORG_TYPE_DISPLAY_JA),
                    }
                ],
            }
        ],
        "name": hosp_name,
        "telecom": [{"system": "phone", "value": "03-1234-5678"}],
        "address": [{"text": "Tokyo"}],
        "partOf": {"reference": "Organization/hospital-main"}
    }
    entries.append(_entry(root_org_ecs))

    # Main-building Location — referenced by PractitionerRole.location fallback
    # (CY8-07) for staff without a ward assignment. Session 52 fix 2: the
    # reference existed since session 48 but the resource was never emitted
    # (dangling reference, eval reference_integrity FAIL).
    main_loc = {
        "resourceType": "Location",
        "id": "loc-hospital-main",
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Location"]}}
            if is_jp(country)
            else {}
        ),
        "status": "active",
        "name": hosp_name,
        "type": [
            {
                "coding": [
                    {
                        "system": get_system_uri("hl7-v3-rolecode"),
                        "code": "HOSP",
                        "display": "Hospital",
                    }
                ],
            }
        ],
        "physicalType": {
            "coding": [
                {
                    "system": get_system_uri("hl7-location-physical-type"),
                    "code": "bu",
                    "display": "Building" if not is_jp(country) else "建物",
                }
            ],
        },
        "managingOrganization": {"reference": "Organization/hospital-main"},
    }
    entries.append(_entry(main_loc))

    # Facility-shared generic infusion pump Device — referenced by
    # MedicationAdministration.device for continuous IV infusions (CY8-20).
    # Session 52 fix 2: same dangling-reference closure as loc-hospital-main.
    # Real EHRs reference a shared pump asset rather than issuing one per
    # patient, so a single facility-level Device is clinically appropriate.
    pump_device = {
        "resourceType": "Device",
        "id": "dev-infusion-pump",
        "status": "active",
        "type": {
            "coding": [
                {
                    "system": get_system_uri("snomed-ct"),
                    "code": "433296005",
                    "display": ("輸液ポンプ" if is_jp(country) else "Infusion pump for intravenous fluids"),
                }
            ],
            "text": "汎用輸液ポンプ" if is_jp(country) else "Generic infusion pump",
        },
        "owner": {"reference": "Organization/hospital-main"},
    }
    entries.append(_entry(pump_device))

    # Department Organizations (one per available_department)
    for dept in available:
        display = _dept_display(dept, country)
        dept_org = {
            "resourceType": "Organization",
            "id": f"dept-{dept.replace('_', '-')}",
            **_jp_org_profile,
            "active": True,
            "type": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-organization-type"),
                            "code": "dept",
                            "display": _localize_display("Hospital Department", country, _ORG_TYPE_DISPLAY_JA),
                        }
                    ],
                }
            ],
            "name": display,
            "partOf": {"reference": "Organization/hospital-main"},
        }
        entries.append(_entry(dept_org))
        # CO-5 (session 42 cycle 3): also emit a Location per department so
        # AMB / EMER Encounter.location = Location/loc-dept-{dept} resolves.
        # Previously only ward + bed Locations existed; AMB visits linked
        # to nothing physical.
        dept_loc = {
            "resourceType": "Location",
            "id": f"loc-dept-{dept.replace('_', '-')}",
            # Session 46 chain #2: JP Core Location profile.
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Location"]}}
                if is_jp(country)
                else {}
            ),
            "status": "active",
            "name": display,
            # C4-14 (session 43 cycle 4): Location.type per FHIR spec
            # (HL7 v3-RoleCode _ServiceDeliveryLocationRoleType). Departments
            # are outpatient service delivery locations.
            "type": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-v3-rolecode"),
                            "code": "OUTPHARM" if dept == "pharmacy" else "OF",
                            "display": "Outpatient pharmacy" if dept == "pharmacy" else "Outpatient facility",
                        }
                    ],
                }
            ],
            "physicalType": {
                "coding": [
                    {
                        "system": get_system_uri("hl7-location-physical-type"),
                        "code": "area",
                        "display": "Area" if not is_jp(country) else "エリア",
                    }
                ],
            },
            "managingOrganization": {"reference": f"Organization/dept-{dept.replace('_', '-')}"},
        }
        entries.append(_entry(dept_loc))

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
                # session 59 #299:location-physical-type CS の code "area"
                # の権威 display は "Area"。従来 "Emergency Room" を出していた
                # が HAPI Wrong Display 検出(1 件 v5)。ER 由来の semantic
                # は Location.name / description で保持済。
                phys_display = "Area"
            elif ward == "OPD":
                phys_type = "area"
                phys_display = "Area"  # #299: 同 CS 権威 display
            org_ref = f"Organization/dept-{dept.replace('_', '-')}"
            # C4-14 (session 43 cycle 4): Location.type per HL7 v3-RoleCode.
            if ward == "ER":
                _type_code, _type_disp = "ER", "Emergency room"
            elif ward == "OPD":
                # feedback FB-F7: OUTPT は v3-RoleCode 未定義、OF (Outpatient Facility) 使用
                _type_code, _type_disp = "OF", "Outpatient facility"
            elif ward.startswith("ICU") or ward == "ICU":
                _type_code, _type_disp = "ICU", "Intensive care unit"
            elif "REHAB" in ward.upper() or "回復期" in ward:
                _type_code, _type_disp = "HUACC", "Acute care unit"
            else:
                _type_code, _type_disp = "HU", "Hospital unit"
            ward_loc = {
                "resourceType": "Location",
                "id": f"loc-ward-{ward}",
                # Session 46 chain #2: JP Core Location profile.
                **(
                    {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Location"]}}
                    if is_jp(country)
                    else {}
                ),
                "status": "active",
                "name": (f"{ward}病棟" if is_jp(country) else f"Ward {ward}")
                if ward not in ("ER", "OPD")
                else _localize_display(phys_display, country, _LOCATION_NAME_JA),  # noqa: E501
                "type": [
                    {
                        "coding": [
                            {
                                "system": get_system_uri("hl7-v3-rolecode"),
                                "code": _type_code,
                                "display": _type_disp,
                            }
                        ],
                    }
                ],
                "physicalType": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-location-physical-type"),
                            "code": phys_type,
                            "display": phys_display,
                        }
                    ],
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
                        # Session 46 chain #2: JP Core Location profile.
                        **(
                            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Location"]}}
                            if is_jp(country)
                            else {}
                        ),
                        "status": "active",
                        "name": f"{bed_id}号室" if is_jp(country) else f"Bed {bed_id}",
                        # C4-14 (session 43 cycle 4): Location.type per HL7 v3-RoleCode.
                        "type": [
                            {
                                "coding": [
                                    {
                                        "system": get_system_uri("hl7-v3-rolecode"),
                                        "code": "HU",
                                        "display": "Hospital unit",
                                    }
                                ],
                            }
                        ],
                        "physicalType": {
                            "coding": [
                                {
                                    "system": get_system_uri("hl7-location-physical-type"),
                                    "code": "bd",
                                    "display": "Bed",
                                }
                            ],
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
            "Organization/dept-general-surgery" if "general_surgery" in available else "Organization/hospital-main"
        )
        for i in range(1, n_or + 1):
            or_loc = {
                "resourceType": "Location",
                "id": f"loc-or-{i}",
                # Session 46 chain #2: JP Core Location profile.
                **(
                    {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Location"]}}
                    if is_jp(country)
                    else {}
                ),
                "status": "active",
                "name": (f"手術室 {i}" if is_jp(country) else f"Operating Room {i}"),
                "physicalType": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-location-physical-type"),
                            "code": "ro",
                            "display": "Room",
                        }
                    ],
                },
                "type": [
                    {
                        "coding": [
                            {
                                "system": get_system_uri("hl7-v3-rolecode"),
                                "code": "OR",
                                "display": _localize_display("Operating Room", country, _LOCATION_TYPE_DISPLAY_JA),
                            }
                        ],
                    }
                ],
                "managingOrganization": {"reference": or_org_ref},
            }
            entries.append(_entry(or_loc))

    return {
        "resourceType": "Bundle",
        "id": "facility",
        "type": "collection",
        "entry": entries,
    }
