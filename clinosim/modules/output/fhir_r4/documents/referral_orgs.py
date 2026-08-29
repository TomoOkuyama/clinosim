"""External referring / receiving Organization catalog for JP-CLINS 診療情報提供書.

Issue #924 fix: 100 % of emitted referral letters (LOINC 57133-1) pointed
both 紹介元 (920) and 紹介先 (910) `entry.reference` at
`Organization/hospital-main`, contradicting the narrative text
`紹介先:他院`. Root cause was the absence of any external-Organization
catalog — the emit path defaulted every referral endpoint to the emitting
hospital.

This module owns the read-side of the new
``clinosim/locale/jp/external_organizations.yaml`` catalog:

* ``pick_external_hospital`` returns a deterministic entry for a given
  ``(patient_id, encounter_id)`` pair (RNG-neutral per
  feedback_rng_neutral_additive_field.md — pure sha256 → index modulo,
  no consumption from any master RNG). Same inputs always resolve to the
  same catalog row across runs / platforms.
* ``build_external_org_resource`` renders one catalog entry into a
  fully-formed JP_Organization + JP_Organization_eCS FHIR resource,
  matching the field set the eReferral 920 / 910 slice discriminator
  (`type: profile, path: resolve()`) requires — the same 6-field shape
  that ``hospital-main`` carries in ``encounters/facility.py``.

Sampling constraints:
  * outcomes must be stable across sessions and platforms
  * no numpy / Python ``random`` usage — sha256 only
  * catalog order matters: appending is safe, mid-list insertion rotates
    which encounter maps to which hospital (documented in the YAML)
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.locale.loader import load_external_organizations

# eCS `identifier:medicalInstitutionCode` slice fixedUri — identical to the
# system that ``facility.py`` pins on ``hospital-main``. Extracted here so
# the external-org resources stay byte-identical in shape to the emitting
# hospital and the JP-CLINS slice discriminator accepts either as a valid
# JP_Organization_eCS target.
_JP_INSURANCE_MED_INST_NO_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/insurance-medical-institution-no"
_JP_ORGANIZATION_PROFILE = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Organization"
_JP_ORGANIZATION_ECS_PROFILE = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Organization_eCS"
# Static lastUpdated — external catalog is versioned with the release, not
# per-run; matches the ``hospital-main`` static value pattern (facility.py).
_JP_ORG_STATIC_LAST_UPDATED = "2026-01-01T00:00:00+09:00"

# Sampling salt — distinct from any other per-encounter derived value so the
# referral picker does not collide with an unrelated deterministic salt.
_REFERRAL_SAMPLING_SALT = "referral-external-hospital"


@lru_cache(maxsize=8)
def _catalog(country: str) -> list[dict[str, Any]]:
    """Return the country's external hospital catalog (cached)."""
    return load_external_organizations(country)


def pick_external_hospital(
    patient_id: str,
    encounter_id: str,
    country: str = "JP",
) -> dict[str, Any] | None:
    """Deterministically sample one external hospital for a referral encounter.

    Selection is a sha256 modulo the catalog length — RNG-neutral (no
    consumption from any master RNG, so adding this path does not shift
    any downstream stochastic sequence). Same ``(patient_id, encounter_id)``
    always resolves to the same catalog row, across processes and platforms.

    Returns ``None`` when the catalog is empty (e.g. US, which does not
    ship an ``external_organizations.yaml`` today) — callers must handle
    the no-catalog case and fall back to their prior emit behavior.
    """
    catalog = _catalog(country)
    if not catalog:
        return None
    key = f"{patient_id}::{encounter_id}::{_REFERRAL_SAMPLING_SALT}".encode()
    digest = hashlib.sha256(key).digest()
    idx = int.from_bytes(digest[:8], "big") % len(catalog)
    return catalog[idx]


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
    address_text = f"{prefecture}{city}" if prefecture or city else "日本"
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
        "type": [
            {
                "coding": [
                    {
                        "system": get_system_uri("hl7-organization-type"),
                        "code": entry.get("type_code") or "prov",
                        "display": entry.get("type_display") or "医療機関",
                    }
                ],
            }
        ],
        "name": entry.get("name") or entry["id"],
        "telecom": [{"system": "phone", "value": str(entry.get("phone") or "03-0000-0000"), "use": "work"}],
        "address": [{"use": "work", "text": address_text}],
    }
    return org


def format_referral_destination_text(entry: dict[str, Any], lang: str = "ja") -> str:
    """Return the narrative sentence for the 910 (紹介先) section.

    Fills in the sampled facility name in place of the pre-fix `他院`
    placeholder. English lang emitted for symmetry with the
    template-generator English branch (currently unreachable — JP-CLINS
    eReferral is JP-only — but keeps the helper honest).
    """
    name = entry.get("name") or entry["id"]
    if lang == "ja":
        return f"紹介先:{name}。当該患者の継続加療を目的として本情報提供書を作成する。"
    return f"Referral destination: {name} (continued care)."
