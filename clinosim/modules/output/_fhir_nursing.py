"""FHIR R4 nursing flowsheet builders (category=survey Observations).

NEWS2, GCS, Braden, Morse, ADL (Barthel), and 24h intake/output.
Extracted from _fhir_observations.py in PR3 (AD-55 Module Foundation
Refactor final piece). The ctx-taking builder imports the shared
BundleContext from _fhir_common, so this module never imports back
through the adapter (no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output._fhir_common import (
    BundleContext,
    _loinc_coding,
    _survey_category,
    to_fhir_datetime,
)


def _build_nursing_observations(ctx: BundleContext) -> list[dict]:
    """Build FHIR Observation resources for nursing flowsheet data (category=survey).

    Emits observations for:
    - NEWS2 score (no authoritative LOINC — code.text only)
    - GCS total (LOINC 9269-2)
    - Braden scale total (LOINC 38227-5)
    - Morse fall risk total (LOINC 59460-6) with fall_risk_level in interpretation
    - Barthel index total (LOINC 96761-2)
    - Fluid intake total 24h (LOINC 9108-2)
    - Urine output 24h (LOINC 9192-6)
    - Fluid output total 24h (LOINC 9262-7)
    """
    enc = ctx.primary_enc_id
    lang = resolve_lang(ctx.country)
    subject: dict[str, Any] = {"reference": f"Patient/{ctx.patient_id}"}
    enc_ref: dict[str, Any] | None = (
        {"reference": f"Encounter/{enc}"} if enc else None
    )
    out: list[dict] = []

    def _obs_base(obs_id: str, effective: str | None) -> dict[str, Any]:
        """Return the shared skeleton of a survey Observation."""
        resource: dict[str, Any] = {
            "resourceType": "Observation",
            "id": obs_id,
            "status": "final",
            "category": _survey_category(),
            "subject": subject,
        }
        if enc_ref:
            resource["encounter"] = enc_ref
        if effective:
            resource["effectiveDateTime"] = effective
        return resource

    # --- Vital signs: NEWS2 and GCS ---
    for i, vs in enumerate(ctx.record.get("vital_signs") or []):
        ts = vs.get("timestamp")
        effective = to_fhir_datetime(ts) or None

        news2 = vs.get("news2_score")
        if news2 is not None:
            obs = _obs_base(f"news2-{enc or ctx.patient_id}-{i}", effective)
            # C2-30 (session 42 cycle 2): NEWS2 has an authoritative LOINC
            # code — 90557-9 "National Early Warning Score (NEWS) 2 [Score]"
            # (verified via LOINC search). Was text-only per earlier brief,
            # 118,131 Observations lacked coding as a result.
            obs["code"] = {
                "coding": [_loinc_coding("90557-9", lang)],
                "text": code_lookup("loinc", "90557-9", lang) or "NEWS2",
            }
            obs["valueInteger"] = int(news2)
            out.append(obs)

        gcs = vs.get("gcs_score")
        if gcs is not None:
            obs = _obs_base(f"gcs-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("9269-2", lang)],
                "text": code_lookup("loinc", "9269-2", lang) or "Glasgow coma score total",
            }
            obs["valueInteger"] = int(gcs)
            out.append(obs)

    # --- Nursing risk assessments: Braden and Morse ---
    for i, nra in enumerate(ctx.record.get("nursing_risk_assessments") or []):
        nra_date = nra.get("date")
        effective = to_fhir_datetime(nra_date) or None

        braden = nra.get("braden_total")
        if braden is not None:
            obs = _obs_base(f"braden-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("38227-5", lang)],
                "text": code_lookup("loinc", "38227-5", lang) or "Braden scale total score",
            }
            obs["valueInteger"] = int(braden)
            out.append(obs)

        morse = nra.get("morse_total")
        if morse is not None:
            obs = _obs_base(f"morse-{enc or ctx.patient_id}-{i}", effective)
            morse_text = (
                code_lookup("loinc", "59460-6", lang) or "Fall risk total [Morse Fall Scale]"
            )
            obs["code"] = {
                "coding": [_loinc_coding("59460-6", lang)],
                "text": morse_text,
            }
            obs["valueInteger"] = int(morse)
            fall_level = nra.get("fall_risk_level")
            if fall_level:
                # Clinosim Morse risk bands ("low"/"moderate"/"high") → HL7 v3
                # ObservationInterpretation L / N / H.
                _fall_interp: dict[str, tuple[str, str, str]] = {
                    "low": ("L", "Low", "低リスク"),
                    "moderate": ("N", "Normal", "中リスク"),
                    "high": ("H", "High", "高リスク"),
                }
                code_val, display_en, display_ja = _fall_interp.get(
                    str(fall_level).lower(), ("N", "Normal", "通常")
                )
                interp_display = display_ja if is_jp(ctx.country) else display_en
                interp_text = (
                    f"転倒リスク: {fall_level}"
                    if is_jp(ctx.country)
                    else f"Fall risk: {fall_level}"
                )
                obs["interpretation"] = [{
                    "coding": [{
                        "system": get_system_uri("hl7-observation-interpretation"),
                        "code": code_val,
                        "display": interp_display,
                    }],
                    "text": interp_text,
                }]
            out.append(obs)

    # --- ADL assessments: Barthel index ---
    for i, adl in enumerate(ctx.record.get("adl_assessments") or []):
        adl_date = adl.get("date")
        effective = to_fhir_datetime(adl_date) or None

        barthel = adl.get("barthel_score")
        if barthel is not None:
            obs = _obs_base(f"barthel-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("96761-2", lang)],
                "text": code_lookup("loinc", "96761-2", lang) or "Total score Barthel Index",
            }
            obs["valueInteger"] = int(barthel)
            out.append(obs)

    # --- Intake and output records ---
    for i, io in enumerate(ctx.record.get("intake_output_records") or []):
        io_date = io.get("date")
        effective = to_fhir_datetime(io_date) or None

        # Fluid intake total 24h = iv + oral + other (LOINC 9108-2)
        iv_ml = io.get("intake_iv_ml") or 0
        oral_ml = io.get("intake_oral_ml") or 0
        other_in_ml = io.get("intake_other_ml") or 0
        intake_total = iv_ml + oral_ml + other_in_ml
        if intake_total > 0:
            obs = _obs_base(f"intake-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("9108-2", lang)],
                "text": code_lookup("loinc", "9108-2", lang) or "Fluid intake total 24 hour",
            }
            obs["valueQuantity"] = {
                "value": int(intake_total),
                "unit": "mL",
                "system": get_system_uri("ucum"),
                "code": "mL",
            }
            out.append(obs)

        # Urine output 24h (component; LOINC 9192-6)
        urine_ml = io.get("output_urine_ml")
        if urine_ml is not None:
            obs = _obs_base(f"urine-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("9192-6", lang)],
                "text": code_lookup("loinc", "9192-6", lang) or "Urine output 24 hour",
            }
            obs["valueQuantity"] = {
                "value": int(urine_ml),
                "unit": "mL",
                "system": get_system_uri("ucum"),
                "code": "mL",
            }
            out.append(obs)

        # Fluid output total 24h = urine + drain + other (aggregate; LOINC 9262-7)
        drain_ml = io.get("output_drain_ml") or 0
        other_out_ml = io.get("output_other_ml") or 0
        output_total = (urine_ml or 0) + drain_ml + other_out_ml
        if output_total > 0:
            obs = _obs_base(f"output-{enc or ctx.patient_id}-{i}", effective)
            obs["code"] = {
                "coding": [_loinc_coding("9262-7", lang)],
                "text": code_lookup("loinc", "9262-7", lang) or "Fluid output total 24 hour",
            }
            obs["valueQuantity"] = {
                "value": int(output_total),
                "unit": "mL",
                "system": get_system_uri("ucum"),
                "code": "mL",
            }
            out.append(obs)

    return out
