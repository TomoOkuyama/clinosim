"""AllergyIntolerance FHIR R4 builder (Tier 1 #3 α-min-1 Task 9).

Reads CIF record.patient.allergies: list[Allergy] (Task 2 8-field schema).
Emits one AllergyIntolerance resource per Allergy entry.

This is the sole AllergyIntolerance emit path since Task 15.
The legacy _fhir_patient._build_allergy_intolerance (3-field bare schema,
`allergy-{patient_id}-{index:02d}` ID) was removed from _BUNDLE_BUILDERS in Task 15.
_fhir_patient._build_allergy_intolerance is retained as a private utility but not called.

No-drop invariant (CIF → FHIR):
  allergy_id           -> AllergyIntolerance.id (allergy- prefix + patient_id + allergy_id)
  allergen_code        -> AllergyIntolerance.code.coding[SNOMED] + .code.text (via code_lookup)
  category             -> AllergyIntolerance.category[]
  criticality          -> AllergyIntolerance.criticality
  verification_status  -> AllergyIntolerance.verificationStatus
  onset_date           -> AllergyIntolerance.onsetDateTime
  reactions[*]         -> AllergyIntolerance.reaction[*]
    manifestation_snomed -> reaction.manifestation[*].coding[SNOMED] + .text (via code_lookup)
    severity           -> reaction.severity

Canonical constant ownership:
- ALLERGY_ID_PREFIX: clinosim.modules.document (writer-owner), imported here.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import resolve_lang
from clinosim.modules.document import ALLERGY_ID_PREFIX
from clinosim.modules.output._fhir_common import BundleContext

__all__ = [
    "ALLERGY_ID_PREFIX",
    "_bb_allergy_intolerances",
]

_CLINICAL_STATUS_SYSTEM = get_system_uri("hl7-allergyintolerance-clinical")
_VERIFICATION_STATUS_SYSTEM = get_system_uri("hl7-allergyintolerance-verification")

# Canonical display for clinical/verification status (FHIR R4 standard)
_CLINICAL_STATUS_DISPLAY: dict[str, str] = {
    "active": "Active",
    "inactive": "Inactive",
    "resolved": "Resolved",
}
_VERIFICATION_STATUS_DISPLAY: dict[str, str] = {
    "confirmed": "Confirmed",
    "unconfirmed": "Unconfirmed",
    "refuted": "Refuted",
    "entered-in-error": "Entered in Error",
}

# FHIR-valid AllergyIntolerance.category values
_VALID_CATEGORIES = {"medication", "food", "environment", "biologic"}


def _bb_allergy_intolerances(ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one AllergyIntolerance per Allergy in patient.allergies (8-field schema)."""
    patient_data = _o(ctx.record, "patient", {}) or {}
    allergies = _o(patient_data, "allergies", []) or []
    if not allergies:
        return []
    lang = resolve_lang(ctx.country)
    return [
        r for r in (
            _build_allergy_intolerance(a, ctx.patient_id, lang)
            for a in allergies
        )
        if r is not None
    ]


def _build_allergy_intolerance(allergy: Any, patient_id: str, lang: str = "en") -> dict[str, Any] | None:
    """Build one FHIR R4 AllergyIntolerance from an Allergy (dataclass or dict)."""
    allergen_code = _o(allergy, "allergen_code", "") or ""
    if not allergen_code:
        return None

    allergy_id = _o(allergy, "allergy_id", "") or ""
    category_raw = (_o(allergy, "category", "") or "").lower()
    category = category_raw if category_raw in _VALID_CATEGORIES else "medication"
    criticality = _o(allergy, "criticality", "low") or "low"
    verification_status = _o(allergy, "verification_status", "confirmed") or "confirmed"
    onset_date = _o(allergy, "onset_date", None)

    snomed_system = get_system_uri("snomed-ct")

    # Resolve allergen display via code_lookup (locale-aware, AD-30 — CIF
    # stores the code only; import-time validation guarantees every
    # allergen_code in allergens.yaml resolves).
    resolved_display = code_lookup("snomed-ct", allergen_code, lang)

    code: dict[str, Any] = {"text": resolved_display}
    if allergen_code:
        code["coding"] = [{
            "system": snomed_system,
            "code": allergen_code,
            "display": resolved_display,
        }]

    ver_display = _VERIFICATION_STATUS_DISPLAY.get(verification_status, verification_status)
    res: dict[str, Any] = {
        "resourceType": "AllergyIntolerance",
        "id": f"{ALLERGY_ID_PREFIX}{patient_id}-{allergy_id}",
        "clinicalStatus": {
            "coding": [{
                "system": _CLINICAL_STATUS_SYSTEM,
                "code": "active",
                "display": _CLINICAL_STATUS_DISPLAY["active"],
            }],
        },
        "verificationStatus": {
            "coding": [{
                "system": _VERIFICATION_STATUS_SYSTEM,
                "code": verification_status,
                "display": ver_display,
            }],
        },
        "category": [category],
        "criticality": criticality,
        "code": code,
        "patient": {"reference": f"Patient/{patient_id}"},
    }

    if onset_date is not None:
        # Accept both date objects and ISO strings
        if hasattr(onset_date, "isoformat"):
            res["onsetDateTime"] = onset_date.isoformat()
        else:
            res["onsetDateTime"] = str(onset_date)

    # Build reaction[]
    reactions_raw = _o(allergy, "reactions", []) or []
    reactions: list[dict[str, Any]] = []
    for rxn in reactions_raw:
        manifestation_snomed = _o(rxn, "manifestation_snomed", "") or ""
        severity = _o(rxn, "severity", "mild") or "mild"

        # Resolve manifestation display via code_lookup (locale-aware, AD-30 —
        # CIF stores the code only; import-time validation guarantees every
        # manifestation_snomed in allergens.yaml resolves).
        resolved_manifestation = code_lookup("snomed-ct", manifestation_snomed, lang) if manifestation_snomed else ""

        manifestation: dict[str, Any] = {}
        if resolved_manifestation:
            manifestation["text"] = resolved_manifestation
        if manifestation_snomed:
            manifestation["coding"] = [{
                "system": snomed_system,
                "code": manifestation_snomed,
                "display": resolved_manifestation or manifestation_snomed,
            }]

        rxn_entry: dict[str, Any] = {
            "manifestation": [manifestation] if manifestation else [{"text": "Adverse reaction"}],
            "severity": severity,
        }
        reactions.append(rxn_entry)

    if reactions:
        res["reaction"] = reactions

    return res
