"""FHIR R4 HAI Condition builder (AD-55 Module: hai, PR-B).

Reads list[HAIEvent] from ctx.record.extensions["hai"] and emits one
Condition per HAI. Cultures are emitted by the existing
fhir_r4/labs/microbiology.py builder via record.microbiology (no overlap).
Dual coding: US uses ICD-10-CM billable; JP uses WHO ICD-10 4-char
via existing code_mapping_diagnosis/jp.yaml; SNOMED international
common to both. The ctx-taking builder imports the shared
BundleContext from _fhir_common, so this module never imports back
through the adapter (no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import display as registry_display
from clinosim.codes import get_system_uri, system_key_for
from clinosim.countries import lang_for
from clinosim.locale.i18n import t
from clinosim.locale.loader import map_diagnosis_code
from clinosim.modules._shared import get_attr_or_key
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.context import BundleContext


def _extensions_hai_list(ctx: BundleContext) -> list:
    ext = get_attr_or_key(ctx.record, "extensions", {}) or {}
    return ext.get("hai", []) or []


def _bb_hai_conditions(ctx: BundleContext) -> list[dict]:
    """Build FHIR Condition resources from CIF extensions['hai']."""
    hais = _extensions_hai_list(ctx)
    if not hais:
        return []
    country = ctx.country
    lang = lang_for(country)
    out: list[dict] = []
    for h in hais:
        icd_internal = get_attr_or_key(h, "icd10_code", "")
        snomed = get_attr_or_key(h, "snomed_code", "")
        hai_id = get_attr_or_key(h, "hai_id", "")
        enc_id = get_attr_or_key(h, "encounter_id", "")
        onset_date = get_attr_or_key(h, "onset_date", "")
        if not icd_internal or not hai_id:
            continue
        icd_country = map_diagnosis_code(icd_internal, country)
        icd_sys_key = system_key_for("diagnosis", country)
        icd_disp = registry_display(icd_sys_key, icd_country, lang) or ""
        snomed_disp = registry_display("snomed-ct", snomed, lang) or ""
        coding: list[dict[str, Any]] = [
            {
                "system": get_system_uri(icd_sys_key),
                "code": icd_country,
                "display": icd_disp,
            }
        ]
        if snomed:
            coding.append(
                {
                    "system": get_system_uri("snomed-ct"),
                    "code": snomed,
                    "display": snomed_disp,
                }
            )
        # Issue #2742: every Condition starts from the shared skeleton
        # (identifier, JP Core profile, JP eCS diagnosis type, status, category).
        from clinosim.modules.output.fhir_r4.conditions.conditions import _condition_skeleton, _ConditionContext
        from clinosim.modules.output.fhir_r4.labs.microbiology import HAI_EVENT_ID_SYSTEM

        cctx = _ConditionContext(
            patient_id=ctx.patient_id,
            country=ctx.country,
            encounters=list(get_attr_or_key(ctx.record, "encounters", []) or []),
            deceased=bool(get_attr_or_key(ctx.record, "deceased", False)),
            patient_sex="",
        )
        resource: dict[str, Any] = _condition_skeleton(
            cctx,
            condition_id=hai_id,
            structural_key=hai_id,
            diagnosis_type="clinical",
            clinical_status="active",
            category="encounter-diagnosis",
            mapped_code=icd_country,
        )
        resource["identifier"].append({"system": HAI_EVENT_ID_SYSTEM, "value": hai_id})
        resource["code"] = {"coding": coding, "text": icd_disp or snomed_disp}
        resource["encounter"] = encounter_ref(enc_id)
        resource["onsetDateTime"] = onset_date
        # Text-only evidence (CY6-19): an infection diagnosed from culture and course.
        resource["evidence"] = [{"code": [{"text": t("condition_evidence.hai", lang_for(ctx.country))}]}]
        # The encounter's attending records and asserts the diagnosis; no
        # recorder is stated when the encounter has none.
        _att = ""
        for _enc in get_attr_or_key(ctx.record, "encounters", []) or []:
            if get_attr_or_key(_enc, "encounter_id", "") == enc_id:
                _att = str(get_attr_or_key(_enc, "attending_physician_id", "") or "")
                break
        if _att:
            resource["recorder"] = {"reference": f"Practitioner/{_att}"}
            resource["asserter"] = {"reference": f"Practitioner/{_att}"}
        out.append(resource)
    return out
