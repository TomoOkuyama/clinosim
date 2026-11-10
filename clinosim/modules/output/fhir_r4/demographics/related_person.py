"""FHIR RelatedPerson builder for the patient's emergency contact (Issue #3182).

The emergency contact (CIF ``ContactInfo.emergency_contact_*``) is emitted as
a ``RelatedPerson`` that references the patient, not as ``Patient.contact``:
``JP_Patient_eCheckupGeneral`` reserves its single ``Patient.contact`` for the
workplace contact, and RelatedPerson is the FHIR resource for a person related
to the patient (JP Core ``JP_RelatedPerson``, US Core
``us-core-relatedperson``; declared from the profile YAML by the post-process
pass). The structure is the same for every country.

``relationship`` carries the emergency-contact role (``v2-0131#C``) and the
family relationship (``v3-RoleCode``, mapped from the CIF slug by the
``slug_to_code`` block of ``codes/data/hl7-v3-rolecode.yaml``). Both code
systems publish English only, so the coding keeps the English display and
the label in the output language goes to ``text`` when it differs.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from clinosim.codes import slug_to_code
from clinosim.countries import lang_for
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.lib.common import english_display_concept
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

# Opaque ``rp-<12hex>`` id derived from the structural key
# ``{patient_id}-emergency-contact`` (one emergency contact per patient), which
# round-trips on ``identifier[]`` under RELATED_PERSON_KEY_SYSTEM. The patient
# id makes the key unique and stable across runs and encounters, so the
# writer's id de-dup keeps one RelatedPerson per patient.
RELATED_PERSON_ID_PREFIX = "rp-"
RELATED_PERSON_KEY_SYSTEM = structural_key_system("related-person-key")
_EMERGENCY_CONTACT_KEY_SUFFIX = "emergency-contact"

# v2-0131 Contact Role code of an emergency contact.
_EMERGENCY_CONTACT_ROLE = "C"


@lru_cache(maxsize=1)
def _role_code_by_slug() -> dict[str, str]:
    """CIF emergency-contact relationship slug → v3-RoleCode code."""
    return {str(k): str(v) for k, v in slug_to_code("hl7-v3-rolecode").items()}


def _build_emergency_contact_related_person(p: dict, country: str) -> dict[str, Any] | None:
    """The patient's emergency contact as a RelatedPerson, or ``None`` when
    the record names no emergency contact (no name and no phone)."""
    contact = p.get("contact")
    pid = str(p.get("patient_id") or "")
    if not isinstance(contact, dict) or not pid:
        return None
    name = str(contact.get("emergency_contact_name") or "")
    phone = str(contact.get("emergency_contact_phone") or "")
    if not (name or phone):
        return None
    lang = lang_for(country)
    structural_key = f"{pid}-{_EMERGENCY_CONTACT_KEY_SUFFIX}"
    relationship = [english_display_concept("hl7-v2-0131", _EMERGENCY_CONTACT_ROLE, lang)]
    role_code = _role_code_by_slug().get(str(contact.get("emergency_contact_relationship") or ""))
    if role_code:
        relationship.append(english_display_concept("hl7-v3-rolecode", role_code, lang))
    resource: dict[str, Any] = {
        "resourceType": "RelatedPerson",
        "id": derive_opaque_id(RELATED_PERSON_ID_PREFIX, structural_key),
        "identifier": [wrap_as_identifier(structural_key, RELATED_PERSON_KEY_SYSTEM)],
        "active": True,
        "patient": patient_ref(pid),
        "relationship": relationship,
    }
    if name:
        resource["name"] = [{"text": name}]
    if phone:
        resource["telecom"] = [{"system": "phone", "value": phone, "use": "mobile"}]
    return resource


def _bb_related_person(ctx: BundleContext) -> list[dict]:
    """Bundle-builder: the emergency-contact RelatedPerson, if any."""
    resource = _build_emergency_contact_related_person(ctx.patient_data, ctx.country)
    return [resource] if resource else []
