"""FHIR R4 anthropometric Observation builder (Issue #946).

Emits body-measurement Observations — height, weight, BMI, and (for
patients aged ≤ 3 y) head-circumference — on every encounter. Prior
to Issue #946 not a single anthropometric was emitted anywhere in the
generator output; downstream weight-based drug-dose verification, BMI
analytics, and pediatric growth-chart consumers all had zero data.

## Emit shape

One Observation per (patient, encounter, measurement). All four
observations share the following FHIR shape:

- `category = vital-signs` (per HL7 v3-ObservationCategory) — matches
  the sibling HR / SpO2 / temperature vitals emit path.
- `code.coding[0].system = LOINC`.
- `valueQuantity` with UCUM unit (`cm`, `kg`, `kg/m2`).
- `subject` → Patient reference, `encounter` → Encounter reference.
- `effectiveDateTime` = encounter admission datetime.
- Deterministic `id` derived from encounter id + measurement suffix
  (same opaque-id contract as sibling vital-sign builders).

## Value derivation

The values come from
:func:`clinosim.modules.population.encounter_anthropometry.encounter_anthropometrics`
— the one derivation shared with weight-based dosing (Issue #2990), which
documents the adult / pediatric growth-percentile model and its
RNG-neutral (SHA256-keyed) noise.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import display as registry_display
from clinosim.codes import get_system_uri
from clinosim.codes.loinc import loinc_for
from clinosim.codes.ucum import ucum_quantity
from clinosim.countries import lang_for
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key, is_jp
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import dual_slot_concept
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.fhir_time import to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)
from clinosim.modules.output.fhir_r4.lib.jp_profiles import JP_OBSERVATION_COMMON_PROFILE
from clinosim.modules.population.encounter_anthropometry import (
    _parse_encounter_datetime,
    age_at_measurement,
    encounter_anthropometrics,
)

# ---------------------------------------------------------------------------
# LOINC + display metadata for the four emitted body measurements.
# ---------------------------------------------------------------------------

LOINC_BODY_HEIGHT = loinc_for("anthropometric", "body_height")
LOINC_BODY_WEIGHT = loinc_for("anthropometric", "body_weight")
LOINC_HEAD_CIRCUMFERENCE = loinc_for("anthropometric", "head_circumference")
LOINC_BMI = loinc_for("anthropometric", "bmi")

_DISPLAY_EN = {
    LOINC_BODY_HEIGHT: "Body height",
    LOINC_BODY_WEIGHT: "Body weight",
    LOINC_HEAD_CIRCUMFERENCE: "Head Occipital-frontal circumference",
    LOINC_BMI: "Body mass index (BMI) [Ratio]",
}
_DISPLAY_JA = {
    LOINC_BODY_HEIGHT: t("fhir_obs_text.body_height", "ja"),
    LOINC_BODY_WEIGHT: t("fhir_obs_text.body_weight", "ja"),
    LOINC_HEAD_CIRCUMFERENCE: t("fhir_obs_text.head_circumference", "ja"),
    LOINC_BMI: "BMI",
}
_UNIT_UCUM = {
    LOINC_BODY_HEIGHT: "cm",
    LOINC_BODY_WEIGHT: "kg",
    LOINC_HEAD_CIRCUMFERENCE: "cm",
    LOINC_BMI: "kg/m2",
}

# ---------------------------------------------------------------------------
# Opaque id resolver (matches sibling vs-* / blood-* pattern).
# ---------------------------------------------------------------------------

ANTHROPOMETRIC_OBSERVATION_ID_PREFIX = "anthro-"
ANTHROPOMETRIC_OBSERVATION_KEY_SYSTEM = structural_key_system("anthropometric-observation-key")


def _resolve_anthropometric_id(structural_key: str) -> str:
    """FHIR id for one anthropometric Observation.

    Structural key body: ``{encounter_id or patient_id}-{suffix}`` where
    suffix ∈ ``{height, weight, bmi, hc}``. Preserved on
    ``Observation.identifier[]`` for round-trip.
    """
    return derive_opaque_id(ANTHROPOMETRIC_OBSERVATION_ID_PREFIX, structural_key)


# ---------------------------------------------------------------------------
# Observation resource builder.
# ---------------------------------------------------------------------------


def _build_one_observation(
    loinc: str,
    value: float,
    patient_id: str,
    encounter_id: str,
    effective_dt: str,
    country: str,
    suffix: str,
) -> dict[str, Any]:
    """Assemble one FHIR anthropometric Observation resource."""
    display = _DISPLAY_JA[loinc] if is_jp(country) else _DISPLAY_EN[loinc]
    unit = _UNIT_UCUM[loinc]
    structural_key = f"{encounter_id or patient_id}-{suffix}"
    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": _resolve_anthropometric_id(structural_key),
        "identifier": [wrap_as_identifier(structural_key, ANTHROPOMETRIC_OBSERVATION_KEY_SYSTEM)],
        **({"meta": {"profile": [JP_OBSERVATION_COMMON_PROFILE]}} if is_jp(country) else {}),
        "status": "final",
        "category": [dual_slot_concept("hl7-observation-category", "vital-signs", lang_for(country))],
        "code": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": loinc,
                    # Issue #3127: the LOINC display; the label is text.
                    "display": registry_display("loinc", loinc, "en") or _DISPLAY_EN[loinc],
                }
            ],
            "text": display,
        },
        "subject": patient_ref(patient_id),
        "valueQuantity": ucum_quantity(value, unit),
    }
    if effective_dt:
        obs["effectiveDateTime"] = effective_dt
    if encounter_id:
        obs["encounter"] = encounter_ref(encounter_id)
    return obs


def build_anthropometric_observations(
    patient_data: dict,
    encounter: dict,
    country: str,
) -> list[dict[str, Any]]:
    """Return a list of body-height / body-weight / BMI [ / head-circ]
    Observation resources for one encounter. Empty list if the patient
    lacks a usable date_of_birth.
    """
    patient_id = str(patient_data.get("patient_id", "") or "")
    encounter_id = str(get_attr_or_key(encounter, "encounter_id", "") or "")

    raw_dt = get_attr_or_key(encounter, "admission_datetime", None)
    enc_dt = _parse_encounter_datetime(raw_dt)
    age_years, _ = age_at_measurement(patient_data, raw_dt)
    values = encounter_anthropometrics(patient_data, encounter_id, raw_dt, country)

    effective_dt = to_fhir_datetime(enc_dt.isoformat()) if enc_dt else ""

    out: list[dict[str, Any]] = []
    out.append(
        _build_one_observation(
            LOINC_BODY_HEIGHT, values["height_cm"], patient_id, encounter_id, effective_dt, country, "height"
        )
    )
    out.append(
        _build_one_observation(
            LOINC_BODY_WEIGHT, values["weight_kg"], patient_id, encounter_id, effective_dt, country, "weight"
        )
    )
    # Issue #1322: BMI is not a valid metric under age 2 (WHO / AAP: use
    # weight-for-length percentile instead). Suppress the BMI Observation
    # for infants; height + weight alone suffice for growth analytics.
    if age_years >= 2:
        out.append(
            _build_one_observation(LOINC_BMI, values["bmi"], patient_id, encounter_id, effective_dt, country, "bmi")
        )
    if "head_circumference_cm" in values:
        out.append(
            _build_one_observation(
                LOINC_HEAD_CIRCUMFERENCE,
                values["head_circumference_cm"],
                patient_id,
                encounter_id,
                effective_dt,
                country,
                "hc",
            )
        )
    return out


def _bb_anthropometrics(ctx: BundleContext) -> list[dict]:
    """Bundle builder: emit height / weight / BMI (+ head-circ if pediatric)
    for every encounter in the record.

    Registered in ``_BUNDLE_BUILDERS`` next to ``_bb_vitals``.
    """
    out: list[dict] = []
    encounters = ctx.record.get("encounters", []) or []
    patient_data = ctx.patient_data or {}
    for enc in encounters:
        enc_dict = (
            enc
            if isinstance(enc, dict)
            else {
                "encounter_id": getattr(enc, "encounter_id", ""),
                "admission_datetime": getattr(enc, "admission_datetime", None),
            }
        )
        out.extend(build_anthropometric_observations(patient_data, enc_dict, ctx.country))
    return out
