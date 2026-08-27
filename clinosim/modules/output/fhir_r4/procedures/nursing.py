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
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import (
    BundleContext,
    loinc_coding,
    survey_category,
    to_fhir_datetime,
)
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

# === Issue #854 Bucket A row 4 (PR-obs-vs): opaque scoring Observation.id ===
# GCS and NEWS2 vital-derived scoring Observations. Same pattern as
# PR #357 / #863 / #867 / #868 / #869 / #878 (lab Observation) / this-PR
# (vs-* vitals). Each scoring family owns its own PUBLIC key-system URI
# so downstream consumers can distinguish gcs / news2 identifiers at a
# glance; a single generic ``score-observation-key`` would collapse the
# semantic distinction that today's ``gcs-`` / ``news2-`` prefixes carry.
#
# Structural key = pre-#854 id body (without ``gcs-`` / ``news2-`` prefix):
#     ``{enc or patient_id}-{i}``
# where ``i`` is the 0-based index in the ``vital_signs`` list.
#
# Braden / Morse / Barthel / intake / urine / output scoring
# Observations emitted below stay on their pre-#854 compound id in this
# PR — they land in the follow-on PR-obs-standalone (Issue #854 Bucket A
# row 4 continuation) so this PR's diff stays reviewable.
GCS_SCORE_ID_PREFIX = "gcs-"
NEWS2_SCORE_ID_PREFIX = "news2-"
GCS_SCORE_KEY_SYSTEM = structural_key_system("gcs-score-observation-key")
NEWS2_SCORE_KEY_SYSTEM = structural_key_system("news2-score-observation-key")


def _resolve_gcs_score_id(structural_key: str) -> str:
    """Return the FHIR Observation.id for a GCS scoring observation.

    Shape: ``gcs-{sha256(structural_key)[:12]}`` = 16 chars, fixed.
    See :data:`GCS_SCORE_KEY_SYSTEM` for the round-trip identifier.
    """
    return derive_opaque_id(GCS_SCORE_ID_PREFIX, structural_key)


def _resolve_news2_score_id(structural_key: str) -> str:
    """Return the FHIR Observation.id for a NEWS2 scoring observation.

    Shape: ``news2-{sha256(structural_key)[:12]}`` = 18 chars, fixed.
    See :data:`NEWS2_SCORE_KEY_SYSTEM` for the round-trip identifier.
    """
    return derive_opaque_id(NEWS2_SCORE_ID_PREFIX, structural_key)


# === Issue #854 Bucket A row 4 (PR-obs-standalone): remaining nursing families ===
# Each family follows the same pattern as gcs / news2 above (PR-obs-vs).
# Structural key = pre-#854 id body (without prefix): ``{enc or patient_id}-{i}``.
BRADEN_SCORE_ID_PREFIX = "braden-"
MORSE_SCORE_ID_PREFIX = "morse-"
BARTHEL_SCORE_ID_PREFIX = "barthel-"
INTAKE_OBSERVATION_ID_PREFIX = "intake-"
URINE_OUTPUT_OBSERVATION_ID_PREFIX = "urine-"
OUTPUT_OBSERVATION_ID_PREFIX = "output-"

BRADEN_SCORE_KEY_SYSTEM = structural_key_system("braden-score-observation-key")
MORSE_SCORE_KEY_SYSTEM = structural_key_system("morse-score-observation-key")
BARTHEL_SCORE_KEY_SYSTEM = structural_key_system("barthel-score-observation-key")
INTAKE_OBSERVATION_KEY_SYSTEM = structural_key_system("intake-observation-key")
URINE_OUTPUT_OBSERVATION_KEY_SYSTEM = structural_key_system("urine-output-observation-key")
OUTPUT_OBSERVATION_KEY_SYSTEM = structural_key_system("fluid-output-observation-key")


def _resolve_braden_score_id(structural_key: str) -> str:
    return derive_opaque_id(BRADEN_SCORE_ID_PREFIX, structural_key)


def _resolve_morse_score_id(structural_key: str) -> str:
    return derive_opaque_id(MORSE_SCORE_ID_PREFIX, structural_key)


def _resolve_barthel_score_id(structural_key: str) -> str:
    return derive_opaque_id(BARTHEL_SCORE_ID_PREFIX, structural_key)


def _resolve_intake_observation_id(structural_key: str) -> str:
    return derive_opaque_id(INTAKE_OBSERVATION_ID_PREFIX, structural_key)


def _resolve_urine_output_observation_id(structural_key: str) -> str:
    return derive_opaque_id(URINE_OUTPUT_OBSERVATION_ID_PREFIX, structural_key)


def _resolve_output_observation_id(structural_key: str) -> str:
    return derive_opaque_id(OUTPUT_OBSERVATION_ID_PREFIX, structural_key)


def _bb_nursing_observations(ctx: BundleContext) -> list[dict]:
    """Build FHIR Observation resources for nursing flowsheet data (category=survey).

    Emits observations for:
    - NEWS2 score (clinosim custom `nursing-scores` CS — LOINC 2.82 has no
      canonical NEWS2 code; #269 fix)
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
    enc_ref: dict[str, Any] | None = encounter_ref(enc) if enc else None
    # RM-1: primary_nurse_id as fallback performer for
    # nursing-observation Observations whose source record lacks a
    # measured_by field (nursing risk / ADL / intake-output).
    encounters = ctx.record.get("encounters", []) or []
    default_nurse_id = encounters[0].get("primary_nurse_id", "") if encounters else ""
    out: list[dict] = []

    def _obs_base(obs_id: str, effective: str | None, performer_id: str = "") -> dict[str, Any]:
        """Return the shared skeleton of a survey Observation.

        RM-1 (cycle 3 tail): performer forwarded when known
        (nursing assessments carry `measured_by` on the source vital or a
        parallel CIF field on assessments themselves).
        """
        resource: dict[str, Any] = {
            "resourceType": "Observation",
            "id": obs_id,
            # Chain #2: JP Core Observation_Common profile.
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common"]}}
                if is_jp(ctx.country)
                else {}
            ),
            "status": "final",
            "category": survey_category(),
            "subject": subject,
        }
        if enc_ref:
            resource["encounter"] = enc_ref
        if effective:
            resource["effectiveDateTime"] = effective
        if performer_id:
            resource["performer"] = [{"reference": f"Practitioner/{performer_id}"}]
        return resource

    # --- Vital signs: NEWS2 and GCS ---
    for i, vs in enumerate(ctx.record.get("vital_signs") or []):
        ts = vs.get("timestamp")
        effective = to_fhir_datetime(ts) or None

        performer_id = vs.get("measured_by", "") or ""
        news2 = vs.get("news2_score")
        if news2 is not None:
            # Issue #854 Bucket A row 4 (PR-obs-vs): opaque NEWS2 Observation.id.
            _news2_structural_key = f"{enc or ctx.patient_id}-{i}"
            obs = _obs_base(_resolve_news2_score_id(_news2_structural_key), effective, performer_id)
            obs["identifier"] = [wrap_as_identifier(_news2_structural_key, NEWS2_SCORE_KEY_SYSTEM)]
            # Issue #269: NEWS2 does NOT have a canonical LOINC
            # 2.82 code — the previously-used `90557-9` is not in LOINC
            # (the closest entry `90557-0` is unrelated sleep-study data).
            # Emit under a clinosim-owned `nursing-scores` CS instead so
            # validators can either resolve or accept it as a locally-defined
            # coding. Any earlier comment that claimed LOINC coverage
            # here was incorrect.
            _news2_display = code_lookup("clinosim-nursing-scores", "NEWS2", lang) or "NEWS2"
            obs["code"] = {
                "coding": [
                    {
                        "system": get_system_uri("clinosim-nursing-scores"),
                        "code": "NEWS2",
                        "display": _news2_display,
                    }
                ],
                "text": _news2_display,
            }
            obs["valueInteger"] = int(news2)
            out.append(obs)

        gcs = vs.get("gcs_score")
        if gcs is not None:
            # Issue #854 Bucket A row 4 (PR-obs-vs): opaque GCS Observation.id.
            _gcs_structural_key = f"{enc or ctx.patient_id}-{i}"
            obs = _obs_base(_resolve_gcs_score_id(_gcs_structural_key), effective, performer_id)
            obs["identifier"] = [wrap_as_identifier(_gcs_structural_key, GCS_SCORE_KEY_SYSTEM)]
            obs["code"] = {
                "coding": [loinc_coding("9269-2", lang)],
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
            _braden_key = f"{enc or ctx.patient_id}-{i}"
            obs = _obs_base(_resolve_braden_score_id(_braden_key), effective, default_nurse_id)
            obs["identifier"] = [wrap_as_identifier(_braden_key, BRADEN_SCORE_KEY_SYSTEM)]
            obs["code"] = {
                "coding": [loinc_coding("38227-5", lang)],
                "text": code_lookup("loinc", "38227-5", lang) or "Braden scale total score",
            }
            obs["valueInteger"] = int(braden)
            out.append(obs)

        morse = nra.get("morse_total")
        if morse is not None:
            _morse_key = f"{enc or ctx.patient_id}-{i}"
            obs = _obs_base(_resolve_morse_score_id(_morse_key), effective, default_nurse_id)
            obs["identifier"] = [wrap_as_identifier(_morse_key, MORSE_SCORE_KEY_SYSTEM)]
            morse_text = code_lookup("loinc", "59460-6", lang) or "Fall risk total [Morse Fall Scale]"
            obs["code"] = {
                "coding": [loinc_coding("59460-6", lang)],
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
                code_val, display_en, display_ja = _fall_interp.get(str(fall_level).lower(), ("N", "Normal", "通常"))
                interp_display = display_ja if is_jp(ctx.country) else display_en
                interp_text = f"転倒リスク: {fall_level}" if is_jp(ctx.country) else f"Fall risk: {fall_level}"
                obs["interpretation"] = [
                    {
                        "coding": [
                            {
                                "system": get_system_uri("hl7-observation-interpretation"),
                                "code": code_val,
                                "display": interp_display,
                            }
                        ],
                        "text": interp_text,
                    }
                ]
            out.append(obs)

    # --- ADL assessments: Barthel index ---
    for i, adl in enumerate(ctx.record.get("adl_assessments") or []):
        adl_date = adl.get("date")
        effective = to_fhir_datetime(adl_date) or None

        barthel = adl.get("barthel_score")
        if barthel is not None:
            _barthel_key = f"{enc or ctx.patient_id}-{i}"
            obs = _obs_base(_resolve_barthel_score_id(_barthel_key), effective, default_nurse_id)
            obs["identifier"] = [wrap_as_identifier(_barthel_key, BARTHEL_SCORE_KEY_SYSTEM)]
            obs["code"] = {
                "coding": [loinc_coding("96761-2", lang)],
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
            _intake_key = f"{enc or ctx.patient_id}-{i}"
            obs = _obs_base(_resolve_intake_observation_id(_intake_key), effective, default_nurse_id)
            obs["identifier"] = [wrap_as_identifier(_intake_key, INTAKE_OBSERVATION_KEY_SYSTEM)]
            obs["code"] = {
                "coding": [loinc_coding("9108-2", lang)],
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
            _urine_key = f"{enc or ctx.patient_id}-{i}"
            obs = _obs_base(_resolve_urine_output_observation_id(_urine_key), effective, default_nurse_id)
            obs["identifier"] = [wrap_as_identifier(_urine_key, URINE_OUTPUT_OBSERVATION_KEY_SYSTEM)]
            obs["code"] = {
                "coding": [loinc_coding("9192-6", lang)],
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
            _output_key = f"{enc or ctx.patient_id}-{i}"
            obs = _obs_base(_resolve_output_observation_id(_output_key), effective, default_nurse_id)
            obs["identifier"] = [wrap_as_identifier(_output_key, OUTPUT_OBSERVATION_KEY_SYSTEM)]
            obs["code"] = {
                "coding": [loinc_coding("9262-7", lang)],
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
