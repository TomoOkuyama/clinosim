"""FHIR code-status (resuscitation status) Observation builder (AD-55 Base)."""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.code_status.engine import load_reference
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import BundleContext, survey_category
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

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
    lang = resolve_lang(ctx.country)
    enc = ctx.primary_enc_id
    observable = load_reference()["observable_snomed"]
    snomed_uri = get_system_uri("snomed-ct")

    def _coding(c: str) -> dict[str, Any]:
        d: dict[str, Any] = {"system": snomed_uri, "code": c}
        disp = code_lookup("snomed-ct", c, lang)
        if disp and disp != c:
            d["display"] = disp
        return d

    encs = ctx.record.get("encounters") or []
    admit = encs[0].get("admission_datetime") if encs else None
    _cs_structural_key = enc or ctx.patient_id
    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": _resolve_code_status_id(_cs_structural_key),
        "identifier": [wrap_as_identifier(_cs_structural_key, CODE_STATUS_KEY_SYSTEM)],
        # chain #2: JP Core Observation_Common profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"]}}
            if is_jp(ctx.country)
            else {}
        ),
        "status": "final",
        "category": survey_category(),
        "code": {"coding": [_coding(observable)]},
        "subject": patient_ref(ctx.patient_id),
        "valueCodeableConcept": {"coding": [_coding(code)]},
    }
    if enc:
        obs["encounter"] = encounter_ref(enc)
    if isinstance(admit, str):
        obs["effectiveDateTime"] = admit
    return [obs]
