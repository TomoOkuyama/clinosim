"""FHIR code-status (resuscitation status) Observation builder (AD-55 Base)."""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.countries import lang_for
from clinosim.modules._shared import is_jp
from clinosim.modules.code_status.engine import load_reference
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import survey_category
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)
from clinosim.modules.output.fhir_r4.lib.jp_profiles import JP_OBSERVATION_COMMON_PROFILE

# === Issue #854 Bucket A row 4 (PR-obs-standalone): opaque code-status id ===
# Structural key = pre-#854 id body: ``{enc or patient_id}``.
CODE_STATUS_ID_PREFIX = "codestatus-"
CODE_STATUS_KEY_SYSTEM = structural_key_system("code-status-observation-key")


def _resolve_code_status_id(structural_key: str) -> str:
    return derive_opaque_id(CODE_STATUS_ID_PREFIX, structural_key)


def _bb_code_status(ctx: BundleContext) -> list[dict]:
    code = ctx.record.get("code_status") or ""
    if not code:
        return []
    lang = lang_for(ctx.country)
    enc = ctx.primary_enc_id
    observable = load_reference()["observable_snomed"]
    snomed_uri = get_system_uri("snomed-ct")

    def _concept(c: str) -> dict[str, Any]:
        # Issue #3026: English SNOMED display on the coding, the label in text.
        d: dict[str, Any] = {"system": snomed_uri, "code": c}
        disp_en = code_lookup("snomed-ct", c, "en")
        if disp_en and disp_en != c:
            d["display"] = disp_en
        concept: dict[str, Any] = {"coding": [d]}
        label = code_lookup("snomed-ct", c, lang)
        if label and label != c and label != disp_en:
            concept["text"] = label
        return concept

    encs = ctx.record.get("encounters") or []
    admit = encs[0].get("admission_datetime") if encs else None
    _cs_structural_key = enc or ctx.patient_id
    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": _resolve_code_status_id(_cs_structural_key),
        "identifier": [wrap_as_identifier(_cs_structural_key, CODE_STATUS_KEY_SYSTEM)],
        # chain #2: JP Core Observation_Common profile.
        **({"meta": {"profile": [JP_OBSERVATION_COMMON_PROFILE]}} if is_jp(ctx.country) else {}),
        "status": "final",
        "category": survey_category(lang_for(ctx.country)),
        "code": _concept(observable),
        "subject": patient_ref(ctx.patient_id),
        "valueCodeableConcept": _concept(code),
    }
    if enc:
        obs["encounter"] = encounter_ref(enc)
    # Issue #2649: the attending who set the status with the patient.
    attending = (encs[0].get("attending_physician_id") if encs else "") or ""
    if attending:
        obs["performer"] = [{"reference": f"Practitioner/{attending}"}]
    if isinstance(admit, str):
        obs["effectiveDateTime"] = admit
    return [obs]
