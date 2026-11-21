"""External referring / receiving Organization catalog for JP-CLINS 診療情報提供書.

Issue #924 fix: 100 % of emitted referral letters (LOINC 57133-1) pointed
both 紹介元 (920) and 紹介先 (910) `entry.reference` at
`Organization/hospital-main`, contradicting the narrative text
`紹介先:他院`. Root cause was the absence of any external-Organization
catalog — the emit path defaulted every referral endpoint to the emitting
hospital.

This module owns the read-side of the new
``clinosim/locale/jp/external_organizations.yaml`` catalog:

* ``pick_external_hospital`` (re-exported from
  ``modules/document/referral_recipient.py``, which the narrative also reads,
  Issue #3460) returns a deterministic entry for a given
  ``(patient_id, encounter_id)`` pair — pure sha256 → index modulo, no
  consumption from any master RNG.
* ``build_external_org_resource`` renders one catalog entry into a
  fully-formed JP_Organization + JP_Organization_eCS FHIR resource,
  matching the field set the eReferral 920 / 910 slice discriminator
  (`type: profile, path: resolve()`) requires — the same 6-field shape
  that ``hospital-main`` carries in ``encounters/facility.py``.

The catalog order matters: appending is safe, mid-list insertion rotates
which encounter maps to which hospital (documented in the YAML).
"""

from __future__ import annotations

from typing import Any

from clinosim.locale.i18n import t
from clinosim.modules.document.referral_recipient import (
    format_referral_destination_text,
    pick_external_hospital,
)
from clinosim.modules.output.fhir_r4.lib.common import dual_slot_concept
from clinosim.modules.output.fhir_r4.lib.jp_profiles import (
    JP_INSURANCE_MEDICAL_INSTITUTION_NO_SYSTEM,
    JP_ORGANIZATION_ECS_PROFILE,
    JP_ORGANIZATION_PROFILE,
)

__all__ = ["build_external_org_resource", "format_referral_destination_text", "pick_external_hospital"]

# eCS `identifier:medicalInstitutionCode` slice fixedUri — identical to the
# system that ``facility.py`` pins on ``hospital-main``. Extracted here so
# the external-org resources stay byte-identical in shape to the emitting
# hospital and the JP-CLINS slice discriminator accepts either as a valid
# JP_Organization_eCS target.
_JP_INSURANCE_MED_INST_NO_SYSTEM = JP_INSURANCE_MEDICAL_INSTITUTION_NO_SYSTEM
_JP_ORGANIZATION_PROFILE = JP_ORGANIZATION_PROFILE
_JP_ORGANIZATION_ECS_PROFILE = JP_ORGANIZATION_ECS_PROFILE
# Static lastUpdated — external catalog is versioned with the release, not
# per-run; matches the ``hospital-main`` static value pattern (facility.py).
_JP_ORG_STATIC_LAST_UPDATED = "2026-01-01T00:00:00+09:00"


def build_external_org_resource(entry: dict[str, Any]) -> dict[str, Any]:
    """Render one catalog entry into a JP_Organization(_eCS) FHIR resource.

    The eReferral 920 / 910 slice discriminator (type: profile, path:
    resolve()) requires the target Organization to declare
    JP_Organization_eCS and carry its 6 required fields
    (meta.lastUpdated, identifier:medicalInstitutionCode, type coding,
    name, telecom.value, address.text). This mirrors what
    ``encounters/facility.py`` emits for ``hospital-main`` so the
    external orgs are structurally interchangeable at the slice level.
    """
    prefecture = ((entry.get("address") or {}).get("prefecture") or "").strip()
    city = ((entry.get("address") or {}).get("city") or "").strip()
    address_text = f"{prefecture}{city}" if prefecture or city else t("fhir_emit_text.country_name", "ja")
    org: dict[str, Any] = {
        "resourceType": "Organization",
        "id": entry["id"],
        "meta": {
            "profile": [_JP_ORGANIZATION_PROFILE, _JP_ORGANIZATION_ECS_PROFILE],
            "lastUpdated": _JP_ORG_STATIC_LAST_UPDATED,
        },
        "identifier": [
            {
                "use": "official",
                "system": _JP_INSURANCE_MED_INST_NO_SYSTEM,
                "value": str(entry.get("institution_code") or ""),
            }
        ],
        "active": True,
        # The external-hospital catalog is per country; its organizations are
        # JP referral destinations, so the label is Japanese (dual slot,
        # Issue #2337: English HL7 display in the coding).
        "type": [
            dual_slot_concept(
                "hl7-organization-type", entry.get("type_code") or "prov", "ja", text=entry.get("type_display") or None
            )
        ],
        "name": entry.get("name") or entry["id"],
        "telecom": [{"system": "phone", "value": str(entry.get("phone") or "03-0000-0000"), "use": "work"}],
        "address": [{"use": "work", "text": address_text}],
    }
    return org
