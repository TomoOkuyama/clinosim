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
from clinosim.modules._shared import get_attr_or_key, resolve_lang
from clinosim.modules.output._fhir_common import BundleContext, _coding_with_display, to_fhir_datetime


def _build_immunizations(ctx: BundleContext) -> list[dict]:
    """Build FHIR Immunization resources from CIF immunizations (CVX codes, AD-30/AD-56).

    Each ImmunizationRecord in ctx.record["immunizations"] maps to one FHIR Immunization.
    Display text is resolved via lookup("cvx", code, lang); never emitted as display == code.
    US output contains no Japanese characters; JP output uses Japanese display when available.
    """
    lang = resolve_lang(ctx.country)
    out: list[dict] = []

    # Any staff whose role includes "physician" or "nurse" can serve as a
    # vaccine administrator. C3-04 (session 42 cycle 3): pick one
    # deterministically per patient so regeneration is byte-identical
    # (AD-16). The choice is stable per patient — reflects a "family doctor"
    # relationship in outpatient practice.
    admin_ids = sorted(
        sid for sid, staff in (ctx.roster_map or {}).items()
        if (staff.get("role", "") or "") in ("physician", "nurse")
    )

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

        resource: dict[str, Any] = {
            "resourceType": "Immunization",
            "id": f"imm-{ctx.patient_id}-{i}",
            "status": status,
            "vaccineCode": vaccine_code,
            "patient": {"reference": f"Patient/{ctx.patient_id}"},
            "occurrenceDateTime": occ_str,
            "primarySource": primary_source,
        }
        # C1-19 (session 41 cycle 1): FHIR R4 requires statusReason when
        # Immunization.status is "not-done". Use v3-ActReason PATOBJ
        # ("patient objection") since clinosim samples refusals rather than
        # medical contraindications; expand YAML → statusReason mapping when
        # the CIF gains an authored reason.
        if status == "not-done":
            # C2-28 (session 42): display resolved via codes/data/
            # hl7-v3-actreason.yaml — was en-only hardcoded string.
            lang = resolve_lang(ctx.country)
            resource["statusReason"] = {
                "coding": [_coding_with_display("hl7-v3-actreason", "PATOBJ", lang)],
                "text": "患者拒否" if lang == "ja" else "Patient refused",
            }
        # C3-03/04/05 (session 42 cycle 3): fill structural Immunization
        # fields that were previously always missing.
        # - lotNumber: pseudo-deterministic per (patient, cvx, occurrence),
        #   mirroring real vaccine-lot tracking. Format = "L-{cvx}-{yyyymm}"
        #   (7-8 chars) is a stub — JP practice records the manufacturer's
        #   printed lot, which clinosim does not simulate; the format is
        #   flagged in NOTE. Better than "" (JP mandatory field).
        # - performer.actor: attending-role staff picked by (patient-id hash
        #   % roster) so re-generation is byte-identical.
        # - reasonCode: text-only "予防接種" / "Vaccination" — the CIF does
        #   not carry a differentiated reason (booster / campaign / etc.).
        if status == "completed":
            _month = str(occ_str)[:7].replace("-", "") if occ_str else ""
            resource["lotNumber"] = f"L-{cvx}-{_month}"
            if admin_ids:
                idx = sum(ord(c) for c in ctx.patient_id) % len(admin_ids)
                resource["performer"] = [{
                    "actor": {"reference": f"Practitioner/{admin_ids[idx]}"},
                }]
        # reasonCode is universal — vaccination is always the reason.
        resource["reasonCode"] = [{
            "text": "予防接種（定期接種）" if lang == "ja" else "Vaccination (routine)",
        }]
        out.append(resource)

    return out
