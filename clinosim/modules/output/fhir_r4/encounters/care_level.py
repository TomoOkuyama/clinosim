"""FHIR JP 要介護度 (long-term-care need level) social-history Observation
builder (AD-55 Base, JP only).

Extracted from the former _fhir_sdoh.py (PR2 G2 SDOH integrity refactor,
2026-06-24) for single-responsibility separation. care_level uses a
custom JP code system (jp-care-level, MHLW 介護保険 区分) and has a
different shape from the LOINC-keyed smoking/alcohol observations, so
it deserves its own file.

Data source: ctx.record.care_level (set by clinosim/modules/care_level/
enricher during post-records pass for JP patients only).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.demographics.smoking_alcohol import _sdoh_effective_datetime
from clinosim.modules.output.fhir_r4.lib.common import (
    BundleContext,
    _social_category,
    _value,
)
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

# === Issue #854 Bucket A row 4 (PR-obs-standalone): opaque care-level id ===
# Structural key = pre-#854 id body (patient id).
# Issue #909: salt hash input with observation-key kind so ``.id`` diverges
# from ``Patient.id`` (which hashes ``patient_id`` unsalted).
_CARE_LEVEL_KEY_KIND = "care-level-observation-key"
CARE_LEVEL_ID_PREFIX = "carelevel-"
CARE_LEVEL_KEY_SYSTEM = structural_key_system(_CARE_LEVEL_KEY_KIND)


def _resolve_care_level_id(structural_key: str) -> str:
    return derive_opaque_id(CARE_LEVEL_ID_PREFIX, f"{_CARE_LEVEL_KEY_KIND}:{structural_key}")


# Issue #733: LOINC observation-identifier for the care-level Observation.
# Selection rationale is in clinosim/codes/data/loinc.yaml (entry 80391-6).
_CARE_LEVEL_LOINC = "80391-6"


def _bb_care_level(ctx: BundleContext) -> list[dict]:
    """JP 要介護度 (long-term-care need level) social-history Observation."""
    code = ctx.record.get("care_level") or ""
    if not code:
        return []
    lang = resolve_lang(ctx.country)
    text = "要介護度" if is_jp(ctx.country) else "Long-term care need level"
    # C2-10: derive effectiveDateTime from earliest
    # encounter admission (mirrors _fhir_smoking_alcohol._sdoh_effective_datetime
    # pattern from C1-12). Care-level is patient-level SDOH, so tying it to the
    # first encounter is appropriate as a proxy for when the level was recorded.
    effective_dt = _sdoh_effective_datetime(ctx)
    _cl_structural_key = ctx.patient_id
    o: dict[str, Any] = {
        "resourceType": "Observation",
        "id": _resolve_care_level_id(_cl_structural_key),
        "identifier": [wrap_as_identifier(_cl_structural_key, CARE_LEVEL_KEY_SYSTEM)],
        # chain #2: JP Core Observation_Common profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"]}}
            if is_jp(ctx.country)
            else {}
        ),
        "status": "final",
        "category": _social_category(ctx.country),
        "code": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": _CARE_LEVEL_LOINC,
                    "display": code_lookup("loinc", _CARE_LEVEL_LOINC, "en"),
                }
            ],
            "text": text,
        },
        "subject": patient_ref(ctx.patient_id),
        "valueCodeableConcept": _value("jp-care-level", code, lang),
    }
    if effective_dt:
        o["effectiveDateTime"] = effective_dt
    return [o]
