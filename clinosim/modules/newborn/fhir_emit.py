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


def _bilirubin_observation_id(patient_id: str, day: int) -> str:
    key = f"bili|{patient_id}|{day}".encode()
    return f"obs-{hashlib.sha256(key).hexdigest()[:12]}"


def _cchd_observation_id(patient_id: str, site: str) -> str:
    key = f"cchd|{patient_id}|{site}".encode()
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


def _bb_newborn_bilirubin(ctx: Any) -> list[dict]:
    """Emit newborn transcutaneous-bilirubin `Observation` resources
    from `record.extensions["newborn"]["bilirubin"]` (populated by
    `enrich_newborn` — engine.build_bilirubin_observations).

    LOINC 58941-6. Category **`exam`** — TcB is a bedside
    bilirubinometer reading (clinician exam finding), NOT a serum lab
    sample. This deliberate category choice keeps the Observation
    outside the JP-CLINS eCS `Observation-eCS-Laboratory` profile
    scope, which mandates a LocalCode slice on every
    `category=laboratory` Observation (not applicable to TcB).
    valueQuantity in `mg/dL` (UCUM).
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
    bili = ((extensions.get("newborn") or {}).get("bilirubin")) or []
    if not bili:
        return []
    patient_id = str(getattr(ctx, "patient_id", "") or "")
    country = str(getattr(ctx, "country", "us") or "us")
    encounter_id = str(getattr(ctx, "primary_enc_id", "") or "")
    is_ja = is_jp(country)
    key_system = "urn:clinosim:identifier:newborn-bilirubin-key"
    out: list[dict] = []
    for e in bili:
        day = int(e.get("day", 0) or 0)
        value = float(e.get("value_mg_dl", 0.0) or 0.0)
        loinc = str(e.get("loinc") or "58941-6")
        struct_key = f"{patient_id}-bili-day-{day}"
        obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": _bilirubin_observation_id(patient_id, day),
            "identifier": [wrap_as_identifier(struct_key, key_system)],
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-observation-category"),
                            "code": "exam",
                            "display": "Exam",
                        }
                    ],
                    "text": "身体所見" if is_ja else "Exam",
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": get_system_uri("loinc"),
                        "code": loinc,
                        "display": "Bilirubin.total [Mass/volume] transcutaneous",
                    }
                ],
                "text": "経皮ビリルビン" if is_ja else "Transcutaneous bilirubin",
            },
            "subject": patient_ref(patient_id),
            "valueQuantity": {
                "value": value,
                "unit": "mg/dL",
                "system": get_system_uri("ucum"),
                "code": "mg/dL",
            },
        }
        ts = e.get("timestamp")
        if ts is not None:
            obs["effectiveDateTime"] = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        if encounter_id:
            obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}
        out.append(obs)
    return out


_CCHD_SITE_SNOMED: dict[str, tuple[str, str]] = {
    "right_hand": ("368208006", "Right upper arm"),
    "foot": ("22335008", "Foot"),
}

_CCHD_SITE_DISPLAY_JA: dict[str, str] = {
    "right_hand": "右手 (pre-ductal)",
    "foot": "足 (post-ductal)",
}


def _bb_newborn_cchd_pulse_ox(ctx: Any) -> list[dict]:
    """Emit CCHD pulse-oximetry screening `Observation` resources from
    `record.extensions["newborn"]["cchd_pulse_ox"]`.

    LOINC 59408-5 (Oxygen saturation in arterial blood by pulse
    oximetry). One Observation per body site (right hand / foot) with
    SNOMED `bodySite` distinguishing pre- vs post-ductal readings.
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
    entries = ((extensions.get("newborn") or {}).get("cchd_pulse_ox")) or []
    if not entries:
        return []
    patient_id = str(getattr(ctx, "patient_id", "") or "")
    country = str(getattr(ctx, "country", "us") or "us")
    encounter_id = str(getattr(ctx, "primary_enc_id", "") or "")
    is_ja = is_jp(country)
    key_system = "urn:clinosim:identifier:newborn-cchd-key"

    out: list[dict] = []
    for e in entries:
        site = str(e.get("site") or "")
        site_snomed = _CCHD_SITE_SNOMED.get(site)
        if site_snomed is None:
            continue
        value = int(e.get("value_pct", 0) or 0)
        loinc = str(e.get("loinc") or "59408-5")
        struct_key = f"{patient_id}-cchd-{site}"
        obs: dict[str, Any] = {
            "resourceType": "Observation",
            "id": _cchd_observation_id(patient_id, site),
            "identifier": [wrap_as_identifier(struct_key, key_system)],
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-observation-category"),
                            "code": "vital-signs",
                            "display": "Vital Signs",
                        }
                    ],
                    "text": "バイタルサイン" if is_ja else "Vital Signs",
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": get_system_uri("loinc"),
                        "code": loinc,
                        "display": "Oxygen saturation in Arterial blood by Pulse oximetry",
                    }
                ],
                "text": (_CCHD_SITE_DISPLAY_JA[site] if is_ja else f"SpO2 ({site.replace('_', ' ')})"),
            },
            "subject": patient_ref(patient_id),
            "valueQuantity": {
                "value": value,
                "unit": "%",
                "system": get_system_uri("ucum"),
                "code": "%",
            },
            "bodySite": {
                "coding": [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": site_snomed[0],
                        "display": site_snomed[1],
                    }
                ],
                "text": _CCHD_SITE_DISPLAY_JA[site] if is_ja else site_snomed[1],
            },
        }
        ts = e.get("timestamp")
        if ts is not None:
            obs["effectiveDateTime"] = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        if encounter_id:
            obs["encounter"] = {"reference": f"Encounter/{encounter_id}"}
        out.append(obs)
    return out
