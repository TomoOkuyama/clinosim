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
from clinosim.modules.output._fhir_common import BundleContext, to_fhir_datetime

__all__ = [
    "ALLERGY_ID_PREFIX",
    "_bb_allergy_intolerances",
]

_CLINICAL_STATUS_SYSTEM = get_system_uri("hl7-allergyintolerance-clinical")
_VERIFICATION_STATUS_SYSTEM = get_system_uri("hl7-allergyintolerance-verification")

# FHIR-valid AllergyIntolerance.category values
_VALID_CATEGORIES = {"medication", "food", "environment", "biologic"}


def _bb_allergy_intolerances(ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one AllergyIntolerance per Allergy in patient.allergies (8-field schema)."""
    patient_data = _o(ctx.record, "patient", {}) or {}
    allergies = _o(patient_data, "allergies", []) or []
    if not allergies:
        return []
    lang = resolve_lang(ctx.country)
    # C3-06/07 (session 42 cycle 3): AllergyIntolerance.recorder = attending
    # physician of first encounter. recordedDate = first encounter admission
    # date when allergy has no onset_date (a chart-registration proxy).
    encounters = _o(ctx.record, "encounters", []) or []
    recorder_ref = ""
    default_recorded_dt = ""
    first_encounter_id = ""
    if encounters:
        att = _o(encounters[0], "attending_physician_id", "") or ""
        if att:
            recorder_ref = f"Practitioner/{att}"
        default_recorded_dt = str(_o(encounters[0], "admission_datetime", "") or "")
        first_encounter_id = _o(encounters[0], "encounter_id", "") or ""
    out: list[dict[str, Any]] = []
    for a in allergies:
        ai = _build_allergy_intolerance(a, ctx.patient_id, lang)
        if ai is None:
            continue
        if recorder_ref:
            ai["recorder"] = {"reference": recorder_ref}
        # Only fill recordedDate if the inner builder didn't already (i.e.,
        # onsetDateTime was absent).
        if "recordedDate" not in ai and default_recorded_dt:
            ai["recordedDate"] = default_recorded_dt[:10]  # YYYY-MM-DD
        # CY7-22 (Chain-7): AllergyIntolerance.encounter — link to the first
        # encounter where the allergy was recorded (allergies are asserted at
        # a specific encounter in real EHRs; clinosim's chart-registration
        # proxy is the first encounter).
        if first_encounter_id:
            ai["encounter"] = {"reference": f"Encounter/{first_encounter_id}"}
        out.append(ai)
    return out


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
    # C1-17 (session 41 cycle 1): read clinical_status from CIF (defaults to
    # "active" when the record predates the field addition).
    clinical_status = _o(allergy, "clinical_status", "active") or "active"
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

    # C5-24 (session 43 cycle 5): AllergyIntolerance status displays now
    # locale-aware. Was hard-coded "en" — JP output leaked English displays.
    ver_display = code_lookup("hl7-allergyintolerance-verification", verification_status, lang)
    clin_display = code_lookup("hl7-allergyintolerance-clinical", clinical_status, lang)
    res: dict[str, Any] = {
        "resourceType": "AllergyIntolerance",
        "id": f"{ALLERGY_ID_PREFIX}{patient_id}-{allergy_id}",
        # Session 46 chain #2: JP Core AllergyIntolerance profile.
        # lang == "ja" is the JP-country signal in this builder's caller chain
        # (BundleContext resolves lang from country in _bb_allergy_intolerances).
        **({"meta": {"profile": [
            "http://jpfhir.jp/fhir/core/StructureDefinition/JP_AllergyIntolerance"
        ]}} if lang == "ja" else {}),
        "clinicalStatus": {
            "coding": [{
                "system": _CLINICAL_STATUS_SYSTEM,
                "code": clinical_status,
                "display": clin_display,
            }],
        },
        "verificationStatus": {
            "coding": [{
                "system": _VERIFICATION_STATUS_SYSTEM,
                "code": verification_status,
                "display": ver_display,
            }],
        },
        # C5-14 (session 43 cycle 5): AllergyIntolerance.type (0..1) —
        # `allergy` for immune-mediated hypersensitivity, `intolerance` for
        # non-immune adverse reactions. FHIR R4 required-binding to
        # http://hl7.org/fhir/allergy-intolerance-type. Default to "allergy"
        # because clinosim's allergen registry (allergens.yaml) is populated
        # with true allergens (penicillin / shellfish / peanut / etc.), not
        # intolerances (lactose intolerance would be a Condition, not AI).
        "type": "allergy",
        "category": [category],
        "criticality": criticality,
        "code": code,
        "patient": {"reference": f"Patient/{patient_id}"},
    }

    if onset_date is not None:
        res["onsetDateTime"] = to_fhir_datetime(onset_date)
        # C3-07 (session 42 cycle 3): recordedDate defaults to onsetDateTime
        # when a distinct recording time is not tracked in CIF. FHIR R4 R0..1
        # recommends this for chart traceability.
        res["recordedDate"] = res["onsetDateTime"]
    else:
        # C3-07 partial (session 42 cycle 3): even without onset_date,
        # patient-lifetime allergies are considered recorded at time of first
        # noticing. Use patient date-of-birth + 20 years as a placeholder
        # (adult typical allergy discovery age).
        pass  # Deferred: needs patient DOB context propagated through ctx.

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
