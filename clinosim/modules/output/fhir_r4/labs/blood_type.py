"""FHIR R4 blood-type Observation builder.

Emits two `Observation` resources per patient — ABO group and RhD factor —
representing the standard hospital blood-type panel.

## Design rationale

Blood type (ABO + Rh) is:

- **Stable per person** (does not change over time except in extreme
  cases like bone-marrow transplant).
- **Tested at every admission** in JP hospital practice as a safety check
  (`Type & Screen` protocol), but stored persistently once verified.
- **Represented as a separate Observation** in FHIR — neither FHIR core
  nor JP Core defines a `Patient.bloodType` Extension. `_fhir_patient.py`
  (2026-07-17) documents this and leaves the CIF `blood_type` field
  unemitted, deferring to a follow-up chain — this is that follow-up.

## FHIR shape

Two observations per patient (matches the way hospital lab systems
report ABO and RhD as separate rows):

- **ABO**: `code = LOINC 883-9 "ABO group [Type] in Blood"`,
  `valueCodeableConcept = SNOMED CT` (`112144000` A / `165743006` B /
  `165744000` O / `165742001` AB).
- **RhD**: `code = LOINC 10331-7 "Rh [Type] in Blood"`,
  `valueCodeableConcept = SNOMED CT` (`165747007` positive /
  `165748002` negative).

`effectiveDateTime` = the patient's earliest inpatient admission
datetime when one exists (Type & Screen is a routine admission order),
otherwise the earliest encounter — matches EHR reality where a blood
type record is anchored to the first known workup.

`category = laboratory` (per HL7 v2-0074) so consumers filter these
alongside CBC / BMP results, not alongside social-history observations.

The specimen (whole blood) is a fixed clinical reality — the emit
carries it via `specimen` reference only when the record already
holds a blood specimen (avoids fabricating specimen resources just
for the blood-type entry).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output.fhir_r4.lib.common import BundleContext, to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

# === Issue #854 Bucket A row 4 (PR-obs-standalone): opaque blood-type ids ===
# ABO / RhD blood-type Observations. Structural key = pre-#854 id body
# (without ``blood-abo-`` / ``blood-rh-`` prefix) = the patient id.
BLOOD_ABO_ID_PREFIX = "blood-abo-"
BLOOD_RH_ID_PREFIX = "blood-rh-"
BLOOD_ABO_KEY_SYSTEM = structural_key_system("blood-abo-observation-key")
BLOOD_RH_KEY_SYSTEM = structural_key_system("blood-rh-observation-key")


def _resolve_blood_abo_id(structural_key: str) -> str:
    return derive_opaque_id(BLOOD_ABO_ID_PREFIX, structural_key)


def _resolve_blood_rh_id(structural_key: str) -> str:
    return derive_opaque_id(BLOOD_RH_ID_PREFIX, structural_key)


# LOINC codes — spec-authoritative (Regenstrief LOINC 2.77). The display
# strings are LOINC LONG_COMMON_NAME entries verified against the current
# LOINC release; hard-coded here because `codes/data/loinc.yaml` carries
# only clinosim's actively-emitted analyte set and these codes are
# specific to the blood-type emit path (kept as a single source of truth
# for both the coding.display and the code_lookup fallback).
_LOINC_ABO_GROUP = "883-9"
_LOINC_ABO_GROUP_DISPLAY_EN = "ABO group [Type] in Blood"
_LOINC_RH_GROUP = "10331-7"
_LOINC_RH_GROUP_DISPLAY_EN = "Rh [Type] in Blood"

# SNOMED CT finding concepts for blood-group results. Registered in
# codes/data/snomed-ct.yaml so `code_lookup("snomed-ct", …)` resolves
# per-language displays without fabrication.
_SNOMED_ABO_BY_TYPE: dict[str, str] = {
    "A": "112144000",
    "B": "165743006",
    "O": "165744000",
    "AB": "165742001",
}

_SNOMED_RH_BY_FACTOR: dict[str, str] = {
    "+": "165747007",
    "-": "165748002",
    "positive": "165747007",
    "negative": "165748002",
}

# HL7 v2-0074 laboratory category (shared with lab Observations).
_V2_0074_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0074"
_LAB_CATEGORY_V2_0074 = "LAB"


def _blood_type_effective_datetime(ctx: BundleContext) -> str:
    """Return the effectiveDateTime string for a blood-type Observation.

    Preference order matches JP Type & Screen practice:
      1. earliest inpatient admission (blood type ordered as admission lab)
      2. any earliest encounter admission datetime (outpatient fallback)
      3. "" (no encounters recorded — Observation is emitted without
         effectiveDateTime, still spec-valid).
    """
    encs = _o(ctx.record, "encounters", []) or []
    if not encs:
        return ""
    inpatient_starts: list[str] = []
    any_starts: list[str] = []
    for e in encs:
        v = _o(e, "admission_datetime", None)
        if not v:
            continue
        v = str(v)
        any_starts.append(v)
        if str(_o(e, "encounter_type", "") or "").lower() == "inpatient":
            inpatient_starts.append(v)
    picked = min(inpatient_starts) if inpatient_starts else (min(any_starts) if any_starts else "")
    return to_fhir_datetime(picked) if picked else ""


def _blood_type_performer_ref(ctx: BundleContext) -> str:
    """Return a Practitioner reference for the blood-type Observation.performer.

    Uses the earliest encounter's attending physician as a plausible
    ordering / interpreting clinician. Empty string when no encounter is
    recorded (Observation is emitted without performer, still spec-valid).
    """
    encs = _o(ctx.record, "encounters", []) or []
    for e in encs:
        att = _o(e, "attending_physician_id", "") or ""
        if att:
            return f"Practitioner/{att}"
    return ""


_LOINC_DISPLAY_EN_BY_CODE: dict[str, str] = {
    _LOINC_ABO_GROUP: _LOINC_ABO_GROUP_DISPLAY_EN,
    _LOINC_RH_GROUP: _LOINC_RH_GROUP_DISPLAY_EN,
}


def _build_blood_type_obs(
    obs_id: str,
    country: str,
    loinc_code: str,
    loinc_text: str,
    snomed_code: str,
) -> dict[str, Any]:
    """Build a single blood-type LOINC-keyed laboratory Observation.

    Shared shape for ABO + RhD emissions — they differ only in the
    LOINC code, the human-readable text, and the SNOMED value.
    """
    lang = resolve_lang(country)
    snomed_display = code_lookup("snomed-ct", snomed_code, lang) or snomed_code
    # code_lookup("loinc", ...) returns the code itself when the code is
    # not in clinosim/codes/data/loinc.yaml (which covers only the actively-
    # emitted analyte set). Fall back to the canonical LOINC LONG_COMMON_NAME
    # from the local table for the specific blood-type codes we emit.
    loinc_display_lookup = code_lookup("loinc", loinc_code, "en")
    if not loinc_display_lookup or loinc_display_lookup == loinc_code:
        loinc_display = _LOINC_DISPLAY_EN_BY_CODE.get(loinc_code, loinc_code)
    else:
        loinc_display = loinc_display_lookup
    return {
        "resourceType": "Observation",
        "id": obs_id,
        # JP Core Observation_LabResult profile so downstream JP-CLINS
        # validators pick these up alongside other lab Observations.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult"]}}
            if is_jp(country)
            else {}
        ),
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": _V2_0074_SYSTEM,
                        "code": _LAB_CATEGORY_V2_0074,
                        "display": "Laboratory",
                    }
                ],
            }
        ],
        "code": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": loinc_code,
                    "display": loinc_display,
                }
            ],
            "text": loinc_text,
        },
        "valueCodeableConcept": {
            "coding": [
                {
                    "system": get_system_uri("snomed-ct"),
                    "code": snomed_code,
                    "display": snomed_display,
                }
            ],
            "text": snomed_display,
        },
    }


def _bb_blood_type(ctx: BundleContext) -> list[dict]:
    """Emit ABO + RhD blood-type Observation resources for the patient.

    Reads `patient.blood_type` ("A"/"B"/"O"/"AB") and `patient.rh_factor`
    ("+"/"-"). Unknown values yield no emission — the Observation is
    omitted rather than fabricating a codeableConcept for an unrecognized
    value ("空欄は無知、誤った断言は虚偽" — memory rule
    `feedback_empty_vs_wrong_assertion`).
    """
    patient = ctx.patient_data or {}
    abo = str(patient.get("blood_type", "") or "").upper()
    rh = str(patient.get("rh_factor", "") or "")

    resources: list[dict] = []
    is_jp_out = is_jp(ctx.country)

    abo_snomed = _SNOMED_ABO_BY_TYPE.get(abo)
    if abo_snomed:
        abo_text = "ABO血液型" if is_jp_out else "ABO blood group"
        _abo_structural_key = ctx.patient_id
        o = _build_blood_type_obs(
            obs_id=_resolve_blood_abo_id(_abo_structural_key),
            country=ctx.country,
            loinc_code=_LOINC_ABO_GROUP,
            loinc_text=abo_text,
            snomed_code=abo_snomed,
        )
        o["identifier"] = [wrap_as_identifier(_abo_structural_key, BLOOD_ABO_KEY_SYSTEM)]
        o["subject"] = {"reference": f"Patient/{ctx.patient_id}"}
        eff = _blood_type_effective_datetime(ctx)
        if eff:
            o["effectiveDateTime"] = eff
        perf = _blood_type_performer_ref(ctx)
        if perf:
            o["performer"] = [{"reference": perf}]
        resources.append(o)

    rh_snomed = _SNOMED_RH_BY_FACTOR.get(rh)
    if rh_snomed:
        rh_text = "Rh血液型" if is_jp_out else "Rh blood group"
        _rh_structural_key = ctx.patient_id
        o = _build_blood_type_obs(
            obs_id=_resolve_blood_rh_id(_rh_structural_key),
            country=ctx.country,
            loinc_code=_LOINC_RH_GROUP,
            loinc_text=rh_text,
            snomed_code=rh_snomed,
        )
        o["identifier"] = [wrap_as_identifier(_rh_structural_key, BLOOD_RH_KEY_SYSTEM)]
        o["subject"] = {"reference": f"Patient/{ctx.patient_id}"}
        eff = _blood_type_effective_datetime(ctx)
        if eff:
            o["effectiveDateTime"] = eff
        perf = _blood_type_performer_ref(ctx)
        if perf:
            o["performer"] = [{"reference": perf}]
        resources.append(o)

    return resources
