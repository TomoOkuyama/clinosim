"""FHIR R4 Immunization builder (CVX-coded adult vaccine history).

Builds FHIR Immunization resources (not Observation; resource type
distinct) from CIF ImmunizationRecord entries. Extracted from
_fhir_observations.py in PR3 (AD-55 Module Foundation Refactor final
piece). The ctx-taking builder imports the shared BundleContext from
_fhir_common, so this module never imports back through the adapter
(no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key, is_jp, resolve_lang
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.lib.common import (
    BundleContext,
    _coding_with_display,
    to_fhir_datetime,
)
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

# === Issue #854 Bucket C (PR-immunization): opaque Immunization.id ===
# Structural key = pre-#854 id body `{patient_id}-{i}` (`imm-` prefix
# stripped); post-#854 every `.id` is `imm-<12hex>` (16 chars, fixed).
# Immunization is stand-alone (no cross-ref cascade). The compound key
# round-trips on `.identifier[]` under IMMUNIZATION_KEY_SYSTEM.
IMMUNIZATION_ID_PREFIX = "imm-"
IMMUNIZATION_KEY_SYSTEM = structural_key_system("immunization-key")


def _resolve_immunization_id(structural_key: str) -> str:
    """Return the opaque FHIR Immunization.id from a structural key.

    Shape: ``imm-{sha256(structural_key)[:12]}`` = 16 chars, fixed.
    """
    return derive_opaque_id(IMMUNIZATION_ID_PREFIX, structural_key)


def _bb_immunizations(ctx: BundleContext) -> list[dict]:
    """Build FHIR Immunization resources from CIF immunizations (CVX codes, AD-30/AD-56).

    Each ImmunizationRecord in ctx.record["immunizations"] maps to one FHIR Immunization.
    Display text is resolved via lookup("cvx", code, lang); never emitted as display == code.
    US output contains no Japanese characters; JP output uses Japanese display when available.
    """
    lang = resolve_lang(ctx.country)
    out: list[dict] = []

    for i, imm in enumerate(ctx.record.get("immunizations") or []):
        cvx = get_attr_or_key(imm, "vaccine_cvx", "")
        occurrence = get_attr_or_key(imm, "occurrence_date", "")
        status = get_attr_or_key(imm, "status", "completed")
        primary_source = get_attr_or_key(imm, "primary_source", True)

        if not cvx:
            continue

        display = code_lookup("cvx", cvx, lang)
        coding: dict[str, Any] = {"system": get_system_uri("cvx"), "code": cvx}
        if display and display != cvx:
            coding["display"] = display

        vaccine_code: dict[str, Any] = {"coding": [coding]}
        if display and display != cvx:
            vaccine_code["text"] = display

        # occurrence_date may be a date object or ISO string; normalize via FP-UNIFY-2 helper
        occ_str = to_fhir_datetime(occurrence)

        _imm_structural_key = f"{ctx.patient_id}-{i}"
        resource: dict[str, Any] = {
            "resourceType": "Immunization",
            "id": _resolve_immunization_id(_imm_structural_key),
            "identifier": [wrap_as_identifier(_imm_structural_key, IMMUNIZATION_KEY_SYSTEM)],
            # Chain #2: JP Core Immunization profile.
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Immunization"]}}
                if is_jp(ctx.country)
                else {}
            ),
            "status": status,
            "vaccineCode": vaccine_code,
            "patient": patient_ref(ctx.patient_id),
            "occurrenceDateTime": occ_str,
            # C5-13: Immunization.recorded (0..1) —
            # timestamp of registry entry. Defaults to occurrence_date for
            # historical entries (JP 予防接種台帳 practice: recorded on the
            # day of administration for real-time entry). Distinct from
            # occurrenceDateTime for future workflow support where recorded
            # differs from performed (e.g. late data entry).
            "recorded": occ_str,
            "primarySource": primary_source,
        }
        # C1-19: FHIR R4 requires statusReason when
        # Immunization.status is "not-done". Use v3-ActReason PATOBJ
        # ("patient objection") since clinosim samples refusals rather than
        # medical contraindications; expand YAML → statusReason mapping when
        # the CIF gains an authored reason.
        if status == "not-done":
            # C2-28: display resolved via codes/data/
            # hl7-v3-actreason.yaml — was en-only hardcoded string.
            lang = resolve_lang(ctx.country)
            resource["statusReason"] = {
                "coding": [_coding_with_display("hl7-v3-actreason", "PATOBJ", lang)],
                "text": "患者拒否" if lang == "ja" else "Patient refused",
            }
        # C3-05: reasonCode is universal — vaccination
        # is always the reason. text-only per AD-30 (no fabricated coding).
        resource["reasonCode"] = [
            {
                "text": "予防接種（定期接種）" if lang == "ja" else "Vaccination (routine)",
            }
        ]
        # RM-3: lot_number + administered_by now populated in CIF
        # (nurse roster-based). Emit only when present — no fabrication.
        lot = get_attr_or_key(imm, "lot_number", "") or ""
        if lot:
            resource["lotNumber"] = lot
        admin_by = get_attr_or_key(imm, "administered_by", "") or ""
        if admin_by:
            resource["performer"] = [
                {
                    "actor": {"reference": f"Practitioner/{admin_by}"},
                }
            ]
        # CY7-20/21/22 (Chain-7): standard vaccine administration mechanics.
        # All adult IM vaccines follow the same pattern: 0.5mL IM into left
        # deltoid (SNOMED 368208006). Not fabricated — this is universal
        # adult vaccine administration protocol per CDC ACIP + JP 予防接種
        # ガイドライン. Only omitted for not-done entries.
        if status != "not-done":
            resource["site"] = {
                "coding": [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": "368208006",
                        "display": "左三角筋" if lang == "ja" else "Left deltoid",
                    }
                ],
            }
            resource["route"] = {
                "coding": [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": "78421000",
                        "display": "筋肉内注射" if lang == "ja" else "Intramuscular route",
                    }
                ],
            }
            resource["doseQuantity"] = {
                "value": 0.5,
                "unit": "mL",
                "system": "http://unitsofmeasure.org",
                "code": "mL",
            }
        out.append(resource)

    return out
