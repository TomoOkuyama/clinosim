"""FHIR bundle-builders owned by `clinosim.modules.newborn` (#1252 N4+).

Follows the `_bb_*` convention documented in
`clinosim/modules/output/README.md` — one function per bundle-builder,
imports registered in the FHIR adapter's `_BUNDLE_BUILDERS` list. Emit
logic stays inside the newborn module (rather than moving to
`fhir_r4/labs/` etc.) so all newborn-specific resource shapes live in
one place; the adapter only imports.
"""

from __future__ import annotations

import hashlib
from typing import Any

_APGAR_MINUTE_TO_LOINC: dict[int, str] = {
    1: "9271-8",
    5: "9274-2",
    # 10-min score exists (LOINC 9273-4) but only ordered for infants
    # who needed resuscitation — out of scope for the well-newborn slice.
}

_APGAR_MINUTE_DISPLAY_EN: dict[int, str] = {
    1: "1 minute Apgar Score",
    5: "5 minute Apgar Score",
}

_APGAR_MINUTE_DISPLAY_JA: dict[int, str] = {
    1: "アプガースコア (1 分)",
    5: "アプガースコア (5 分)",
}


def _apgar_observation_id(patient_id: str, minute: int) -> str:
    key = f"apgar|{patient_id}|{minute}".encode()
    return f"obs-{hashlib.sha256(key).hexdigest()[:12]}"


def _bb_newborn_apgar(ctx: Any) -> list[dict]:
    """Emit Apgar score `Observation` resources for newborns.

    Reads `record.extensions["newborn"]["apgar"]` (populated by the
    newborn enricher — engine.build_apgar_scores). Standard neonatal
    assessment: LOINC 9271-8 (1 min) / 9274-2 (5 min), category
    survey, valueQuantity 0-10 unitless {score}.

    No-op for records that carry no Apgar entries (non-newborn / older
    CIF fixtures / opt-out).
    """
    from clinosim.codes import get_system_uri
    from clinosim.modules._shared import is_jp
    from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
    from clinosim.modules.output.fhir_r4.lib.ids import wrap_as_identifier

    record = getattr(ctx, "record", None) or {}
    if isinstance(record, dict):
        extensions = record.get("extensions", {}) or {}
    else:
        extensions = getattr(record, "extensions", {}) or {}
    apgar_list = ((extensions.get("newborn") or {}).get("apgar")) or []
    if not apgar_list:
        return []

    patient_id = str(getattr(ctx, "patient_id", "") or "")
    if not patient_id:
        return []
    country = str(getattr(ctx, "country", "us") or "us")
    encounter_id = str(getattr(ctx, "primary_enc_id", "") or "")
    is_ja = is_jp(country)
    key_system = "urn:clinosim:identifier:apgar-observation-key"

    out: list[dict] = []
    for entry in apgar_list:
        minute = int(entry.get("minute", 0) or 0)
        score = int(entry.get("score", 0) or 0)
        loinc = _APGAR_MINUTE_TO_LOINC.get(minute)
        if not loinc:
            continue
        struct_key = f"{patient_id}-apgar-{minute}m"
        display = (_APGAR_MINUTE_DISPLAY_JA if is_ja else _APGAR_MINUTE_DISPLAY_EN)[minute]
        obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": _apgar_observation_id(patient_id, minute),
            "identifier": [wrap_as_identifier(struct_key, key_system)],
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-observation-category"),
                            "code": "survey",
                            "display": "Survey",
                        }
                    ],
                    "text": "Survey" if not is_ja else "評価スコア",
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": get_system_uri("loinc"),
                        "code": loinc,
                        "display": _APGAR_MINUTE_DISPLAY_EN[minute],
                    }
                ],
                "text": display,
            },
            "subject": patient_ref(patient_id),
            "valueQuantity": {
                "value": score,
                # Apgar is a unitless integer score 0-10; UCUM
                # convention is `{score}` (curly-braced dimensionless).
                "unit": "{score}",
                "system": get_system_uri("ucum"),
                "code": "{score}",
            },
        }
        ts = entry.get("timestamp")
        if ts is not None:
            # `datetime` from build_apgar_scores; convert if needed.
            iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            obs["effectiveDateTime"] = iso
        if encounter_id:
            obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}
        out.append(obs)
    return out
