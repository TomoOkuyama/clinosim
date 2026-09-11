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


def _metabolic_screen_sr_id(patient_id: str) -> str:
    key = f"nmscr-sr|{patient_id}".encode()
    return f"sr-{hashlib.sha256(key).hexdigest()[:12]}"


def _metabolic_screen_specimen_id(patient_id: str) -> str:
    key = f"nmscr-spec|{patient_id}".encode()
    return f"spec-{hashlib.sha256(key).hexdigest()[:12]}"


def _metabolic_screen_dr_id(patient_id: str) -> str:
    key = f"nmscr-dr|{patient_id}".encode()
    return f"dr-{hashlib.sha256(key).hexdigest()[:12]}"


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


# ═════════════════════════════════════════════════════════════════════
# #1252 N6b: metabolic-screen full FHIR shape (ServiceRequest +
# Specimen + DiagnosticReport). The Procedure resource emitted for the
# physical heel-stick event stays on `record.procedures` and flows
# through the shared `_bb_procedures` builder; these three sibling
# resources add the diagnostic-workflow evidence a downstream consumer
# expects when querying ServiceRequest.ndjson / Specimen.ndjson /
# DiagnosticReport.ndjson for a newborn screening panel.
# Per-analyte Observations are deferred to a follow-up sub-scope.
# ═════════════════════════════════════════════════════════════════════


def _read_metabolic_screen_ext(ctx: Any) -> tuple[dict[str, Any], str, str, bool] | None:
    """Shared preamble for the three N6b bundle-builders. Returns
    ``(ext_dict, patient_id, encounter_id, is_ja)`` or None on no-op.
    """
    from clinosim.modules._shared import is_jp

    record = getattr(ctx, "record", None) or {}
    if isinstance(record, dict):
        extensions = record.get("extensions", {}) or {}
    else:
        extensions = getattr(record, "extensions", {}) or {}
    ext = ((extensions.get("newborn") or {}).get("metabolic_screen")) or {}
    if not ext:
        return None
    patient_id = str(getattr(ctx, "patient_id", "") or "") or str(ext.get("patient_id", "") or "")
    if not patient_id:
        return None
    country = str(getattr(ctx, "country", "us") or "us")
    encounter_id = str(getattr(ctx, "primary_enc_id", "") or "") or str(ext.get("encounter_id", "") or "")
    return ext, patient_id, encounter_id, is_jp(country)


def _iso(dt: Any) -> str:
    if dt is None:
        return ""
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


def _bb_newborn_metabolic_screen_service_request(ctx: Any) -> list[dict]:
    """Emit the newborn tandem-MS screen `ServiceRequest` (#1252 N6b).

    LOINC 54089-8 "Newborn screening panel American Health Information
    Community (AHIC)" as both category-coded (SNOMED 108252007
    "Laboratory procedure") and per-order code. status=completed,
    intent=order — this is a retrospective evidence emit for a screen
    that already happened during the birth admission.
    """
    from clinosim.codes import get_system_uri
    from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref

    parsed = _read_metabolic_screen_ext(ctx)
    if parsed is None:
        return []
    ext, patient_id, encounter_id, is_ja = parsed

    sr_id = _metabolic_screen_sr_id(patient_id)
    order_loinc = str(ext.get("order_loinc") or "54089-8")
    order_display = str(ext.get("order_display") or "Newborn screening panel")
    order_display_ja = str(ext.get("order_display_ja") or order_display)
    cat_code = str(ext.get("order_category_code") or "108252007")
    cat_display = str(ext.get("order_category_display") or "Laboratory procedure")

    resource: dict[str, Any] = {
        "resourceType": "ServiceRequest",
        "id": sr_id,
        "identifier": [
            {
                "system": "urn:clinosim:identifier:newborn-metabolic-screen-sr-key",
                "value": f"{patient_id}-nmscr-sr",
            }
        ],
        "status": "completed",
        "intent": "order",
        "category": [
            {
                "coding": [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": cat_code,
                        "display": cat_display,
                    }
                ],
                "text": cat_display,
            }
        ],
        "code": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": order_loinc,
                    "display": order_display,
                }
            ],
            "text": order_display_ja if is_ja else order_display,
        },
        "subject": patient_ref(patient_id),
    }
    ordered = ext.get("ordered_datetime")
    if ordered is not None:
        resource["authoredOn"] = _iso(ordered)
    collected = ext.get("collected_datetime")
    if collected is not None:
        resource["occurrenceDateTime"] = _iso(collected)
    if encounter_id:
        resource["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    return [resource]


def _bb_newborn_metabolic_screen_specimen(ctx: Any) -> list[dict]:
    """Emit the heel-stick capillary-blood `Specimen` for the metabolic
    screen (#1252 N6b). SNOMED 122554006 "Capillary blood specimen".
    Body site + collection method emit as text only (no SNOMED coding)
    — the repo's `feedback_verify_fhir_profile_uri_from_spec` rule
    forbids fabricating codes, and verified codes for "heel structure"
    / "heel-stick collection method" are not available on the tx
    servers used elsewhere in this codebase. Text-only is honest and
    FHIR-spec-conformant.
    """
    from clinosim.codes import get_system_uri
    from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref

    parsed = _read_metabolic_screen_ext(ctx)
    if parsed is None:
        return []
    ext, patient_id, _encounter_id, is_ja = parsed

    spec_id = _metabolic_screen_specimen_id(patient_id)
    type_code = str(ext.get("specimen_type_code") or "122554006")
    type_display = str(ext.get("specimen_type_display") or "Capillary blood specimen")
    type_display_ja = str(ext.get("specimen_type_display_ja") or type_display)

    body_site_text = str(
        ext.get("specimen_body_site_ja" if is_ja else "specimen_body_site_en") or ("踵" if is_ja else "Heel")
    )
    method_text = str(
        ext.get("specimen_method_ja" if is_ja else "specimen_method_en")
        or ("踵採血 (毛細血管採血)" if is_ja else "Heel-stick capillary blood collection")
    )
    collected = ext.get("collected_datetime")

    resource: dict[str, Any] = {
        "resourceType": "Specimen",
        "id": spec_id,
        "identifier": [
            {
                "system": "urn:clinosim:identifier:newborn-metabolic-screen-specimen-key",
                "value": f"{patient_id}-nmscr-spec",
            }
        ],
        "status": "available",
        "type": {
            "coding": [
                {
                    "system": get_system_uri("snomed-ct"),
                    "code": type_code,
                    "display": type_display,
                }
            ],
            "text": type_display_ja if is_ja else type_display,
        },
        "subject": patient_ref(patient_id),
        "collection": {
            "bodySite": {"text": body_site_text},
            "method": {"text": method_text},
        },
    }
    if collected is not None:
        resource["collection"]["collectedDateTime"] = _iso(collected)
    return [resource]


def _bb_newborn_metabolic_screen_diagnostic_report(ctx: Any) -> list[dict]:
    """Emit the aggregate `DiagnosticReport` for the newborn tandem-MS
    metabolic screen (#1252 N6b). LOINC 54089-8, category laboratory
    (hl7 v2-0074 "LAB"), `conclusionCode` carrying the SNOMED
    pass / refer outcome from the shared sub-seed
    (`build_metabolic_screen_workflow_data`). Per-analyte results
    (`.result[]`) are a follow-up sub-scope; this report ships the
    overall verdict.
    """
    from clinosim.codes import get_system_uri
    from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref

    parsed = _read_metabolic_screen_ext(ctx)
    if parsed is None:
        return []
    ext, patient_id, encounter_id, is_ja = parsed

    dr_id = _metabolic_screen_dr_id(patient_id)
    sr_id = _metabolic_screen_sr_id(patient_id)
    spec_id = _metabolic_screen_specimen_id(patient_id)

    dr_loinc = str(ext.get("dr_code_loinc") or "54089-8")
    dr_display = str(ext.get("dr_code_display") or "Newborn screening panel")
    dr_display_ja = str(ext.get("dr_code_display_ja") or dr_display)
    dr_cat_code = str(ext.get("dr_category_code") or "LAB")
    dr_cat_display = str(ext.get("dr_category_display") or "Laboratory")

    outcome_code = str(ext.get("outcome_code") or "")
    outcome_key = str(ext.get("outcome_key") or "")
    if outcome_key == "pass":
        conclusion_en = "Pass — no significant abnormalities detected across the screening panel."
        conclusion_ja = "陰性 (パス) — スクリーニングパネル全項目で異常所見なし。"
    else:
        conclusion_en = (
            "Refer — one or more screening panel results were flagged; follow-up confirmatory testing indicated."
        )
        conclusion_ja = "陽性 (要精査) — スクリーニングパネルの一部で異常所見あり、確認検査を推奨。"

    resource: dict[str, Any] = {
        "resourceType": "DiagnosticReport",
        "id": dr_id,
        "identifier": [
            {
                "system": "urn:clinosim:identifier:newborn-metabolic-screen-dr-key",
                "value": f"{patient_id}-nmscr-dr",
            }
        ],
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": get_system_uri("hl7-diagnostic-service-section"),
                        "code": dr_cat_code,
                        "display": dr_cat_display,
                    }
                ],
                "text": dr_cat_display,
            }
        ],
        "code": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": dr_loinc,
                    "display": dr_display,
                }
            ],
            "text": dr_display_ja if is_ja else dr_display,
        },
        "subject": patient_ref(patient_id),
        "basedOn": [{"reference": f"ServiceRequest/{sr_id}"}],
        "specimen": [{"reference": f"Specimen/{spec_id}"}],
        "conclusion": conclusion_ja if is_ja else conclusion_en,
    }
    if outcome_code:
        resource["conclusionCode"] = [
            {
                "coding": [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": outcome_code,
                        # SNOMED outcome displays match the hearing-screen
                        # and Procedure.outcome slots emitted elsewhere
                        # for the same codes (385669000 / 385671000).
                        "display": ("Successful" if outcome_key == "pass" else "Unsuccessful"),
                    }
                ],
                "text": ("陰性 (パス)" if is_ja else "Pass")
                if outcome_key == "pass"
                else ("要精査" if is_ja else "Refer"),
            }
        ]
    collected = ext.get("collected_datetime")
    if collected is not None:
        resource["effectiveDateTime"] = _iso(collected)
        # Report issued 1 h after collection (nominal tandem-MS turnaround
        # is 24-72 h; this MVP slice uses 1 h so the timestamps stay
        # inside the birth-admission window regardless of LOS). Handle
        # both datetime (in-memory enricher path) and str (post-CIF-JSON
        # round-trip path) inputs — CIFReader deserializes datetimes as
        # naive ISO strings, so we parse before adding.
        from datetime import datetime as _dt
        from datetime import timedelta as _td

        if isinstance(collected, _dt):
            issued_dt = collected + _td(hours=1)
        else:
            try:
                issued_dt = _dt.fromisoformat(str(collected)) + _td(hours=1)
            except ValueError:
                issued_dt = None
        resource["issued"] = _iso(issued_dt) if issued_dt is not None else _iso(collected)
    if encounter_id:
        resource["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    return [resource]
