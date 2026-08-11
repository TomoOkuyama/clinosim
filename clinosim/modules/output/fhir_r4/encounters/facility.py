"""FHIR R4 facility master bundle builder (Organization + Location) (FA-1 facility).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

from clinosim.codes import get_system_uri
from clinosim.modules._shared import is_jp
from clinosim.modules.output.fhir_r4.lib.common import entry
from clinosim.modules.output.fhir_r4.lib.localization import (
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
    #
    # C3-17: emits JP Core `JP_Organization` on JP output (adapter's post-hook
    # doesn't touch the separate facility bundle).
    #
    # Issue #746: previously emitted a SECOND Organization with id
    # `hospital-main-ecs` for JP output, carrying the `JP_Organization_eCS`
    # profile + its 6 required fields, purely so that JP-CLINS eReferral /
    # eDischargeSummary slice discriminators (type: profile, path: resolve())
    # would find an eCS-conformant target. The result was two Organization
    # resources for the same 総合病院 (id + id-ecs), which the eval axis
    # flagged as 1/17 (5.9%) eCS declaration coverage — an inconsistency
    # artefact of the two-Organization workaround.
    #
    # Merged approach: JP output emits ONE `hospital-main` Organization
    # declaring both `JP_Organization` AND `JP_Organization_eCS` profiles,
    # with the eCS-required fields populated inline. `Organization.partOf`
    # is spec-optional (min=0 in the base + `min=-` in the eCS differential,
    # which does not raise it), so a root hospital omits it — self-partOf
    # would be invalid. The 6 references from `documents/composition.py`
    # that previously pointed to `hospital-main-ecs` now resolve to the
    # same unified `hospital-main` resource.
    #
    # eCS-required fields sourced from
    # `StructureDefinition-JP-Organization-eCS.json` (min=1 or MS):
    #   - meta.profile / meta.lastUpdated
    #   - identifier:medicalInstitutionCode (system fixedUri +
    #     10-digit medical-institution-code, placeholder "1300000000" since
    #     hospital_config carries no institutional-code field)
    #   - type.coding.system + code (unchanged — same "prov" already used)
    #   - name / telecom.value / address.text
    # telecom.use / address.use required binding: "home" is forbidden by
    # the spec; "work" is used.
    hosp_name = "総合病院" if is_jp(country) else "Community Hospital"
    root_org: dict = {
        "resourceType": "Organization",
        "id": "hospital-main",
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
    if is_jp(country):
        # Static lastUpdated for determinism — hospital_config has no
        # last_updated field yet. Swap for a config-derived value when
        # institutional metadata lands.
        root_org["meta"] = {
            "profile": [
                "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Organization",
                "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Organization_eCS",
            ],
            "lastUpdated": "2026-01-01T00:00:00+09:00",
        }
        root_org["identifier"] = [
            {
                "use": "official",
                # spec fixedUri: identifier:medicalInstitutionCode.system on
                # JP_Organization_eCS. Placeholder 10-digit value stands in
                # for a real MHLW-assigned code until hospital_config
                # carries one.
                "system": "http://jpfhir.jp/fhir/core/IdSystem/insurance-medical-institution-no",
                "value": "1300000000",
            }
        ]
        root_org["telecom"] = [{"system": "phone", "value": "03-0000-0000", "use": "work"}]
        root_org["address"] = [{"use": "work", "text": "東京都"}]
    entries.append(entry(root_org))

    # Main-building Location — referenced by PractitionerRole.location fallback
    # (CY8-07) for staff without a ward assignment. fix 2: the
    # reference existed since but the resource was never emitted
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
    entries.append(entry(main_loc))

    # Facility-shared generic infusion pump Device — referenced by
    # MedicationAdministration.device for continuous IV infusions (CY8-20).
    # fix 2: same dangling-reference closure as loc-hospital-main.
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
    entries.append(entry(pump_device))

    # Department Organizations (one per available_department)
    # Department orgs use base JP_Organization only (JP output) — they are
    # not JP-CLINS eCS institutions, only intra-hospital sub-organizations.
    _dept_jp_profile = (
        {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Organization"]}}
        if is_jp(country)
        else {}
    )
    for dept in available:
        display = _dept_display(dept, country)
        dept_org = {
            "resourceType": "Organization",
            "id": f"dept-{dept.replace('_', '-')}",
            **_dept_jp_profile,
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
        entries.append(entry(dept_org))
        # CO-5: also emit a Location per department so
        # AMB / EMER Encounter.location = Location/loc-dept-{dept} resolves.
        # Previously only ward + bed Locations existed; AMB visits linked
        # to nothing physical.
        dept_loc = {
            "resourceType": "Location",
            "id": f"loc-dept-{dept.replace('_', '-')}",
            # chain #2: JP Core Location profile.
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Location"]}}
                if is_jp(country)
                else {}
            ),
            "status": "active",
            "name": display,
            # C4-14: Location.type per FHIR spec
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
        entries.append(entry(dept_loc))

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
                # #299:location-physical-type CS の code "area"
                # の権威 display は "Area"。従来 "Emergency Room" を出していた
                # が HAPI Wrong Display 検出(1 件 v5)。ER 由来の semantic
                # は Location.name / description で保持済。
                phys_display = "Area"
            elif ward == "OPD":
                phys_type = "area"
                phys_display = "Area"  # #299: 同 CS 権威 display
            org_ref = f"Organization/dept-{dept.replace('_', '-')}"
            # C4-14: Location.type per HL7 v3-RoleCode.
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
                # chain #2: JP Core Location profile.
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
            entries.append(entry(ward_loc))

            # Bed Location resources for inpatient wards
            if ward not in ("ER", "OPD"):
                bed_count = ward_capacity.get(ward, 0)
                for bed_idx in range(1, bed_count + 1):
                    bed_id = f"{ward}-{bed_idx:02d}"
                    bed_loc = {
                        "resourceType": "Location",
                        "id": f"loc-bed-{bed_id}",
                        # chain #2: JP Core Location profile.
                        **(
                            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Location"]}}
                            if is_jp(country)
                            else {}
                        ),
                        "status": "active",
                        "name": f"{bed_id}号室" if is_jp(country) else f"Bed {bed_id}",
                        # C4-14: Location.type per HL7 v3-RoleCode.
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
                    entries.append(entry(bed_loc))

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
                # chain #2: JP Core Location profile.
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
                # #327 v3-RoleCode CS には "OR" 概念が存在
                # しない(authoritative 確認、v6.1 で 2 件 unknown-code
                # error 発火)。近似 SU (Surgery clinic) は semantic 別
                # 概念 (clinic ≠ room)、fabrication 回避のため coding を
                # drop し text-only CodeableConcept で emit。FHIR R4
                # Location.type binding は preferred strength = coding
                # 無くても spec-valid。
                "type": [{"text": _localize_display("Operating Room", country, _LOCATION_TYPE_DISPLAY_JA)}],
                "managingOrganization": {"reference": or_org_ref},
            }
            entries.append(entry(or_loc))

    return {
        "resourceType": "Bundle",
        "id": "facility",
        "type": "collection",
        "entry": entries,
    }
