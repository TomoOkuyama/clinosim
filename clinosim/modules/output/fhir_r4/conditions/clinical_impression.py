"""ClinicalImpression FHIR R4 builder (Tier 1 #3 α-min-1 Task 9).

Reads CIF record.extensions["clinical_impressions"]: list[ClinicalImpressionRecord].
Emits one ClinicalImpression resource per record.

No-drop invariant (CIF → FHIR):
  impression_id        -> ClinicalImpression.id (ci- prefix)
  encounter_id         -> ClinicalImpression.encounter
  patient_id (from ctx) -> ClinicalImpression.subject
  date                 -> ClinicalImpression.effectiveDateTime
  description          -> ClinicalImpression.description
  summary              -> ClinicalImpression.summary
  investigation_refs[] -> ClinicalImpression.investigation[].item[]
  finding_refs[]       -> ClinicalImpression.finding[].itemReference
  prognosis            -> ClinicalImpression.prognosisCodeableConcept[].text
  practitioner_id      -> ClinicalImpression.assessor

Canonical constant ownership:
- CLINICAL_IMPRESSION_ID_PREFIX: clinosim.modules.document (writer-owner), imported here.
"""

from __future__ import annotations

from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import is_jp
from clinosim.modules.document import CLINICAL_IMPRESSION_ID_PREFIX
from clinosim.modules.output.fhir_r4.lib.common import BundleContext, to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

# === Issue #854 Bucket B (PR-clinical-impression): opaque ClinicalImpression.id ===
# Same pattern as PR #357 / #863 / #867 / #868 / #869 / #878 / #879 /
# #880 / #881 / #882 / #883 / #884 / #885 / #886 / #887. Structural key
# = pre-#854 id body (with `ci-` prefix stripped) — the CIF-side
# ``impression.impression_id`` shape is ``ci-{enc}-{day}``.
CLINICAL_IMPRESSION_KEY_SYSTEM = structural_key_system("clinical-impression-key")


def _resolve_clinical_impression_id(structural_key: str) -> str:
    """Return the opaque FHIR ClinicalImpression.id from a structural key.

    Shape: ``ci-{sha256(structural_key)[:12]}`` = 15 chars, fixed.
    """
    return derive_opaque_id(CLINICAL_IMPRESSION_ID_PREFIX, structural_key)


def clinical_impression_id_for_cif_id(cif_impression_id: str) -> str:
    """Convenience wrapper: opaque CI id from the CIF ``impression_id``."""
    key = (
        cif_impression_id.removeprefix(CLINICAL_IMPRESSION_ID_PREFIX)
        if cif_impression_id.startswith(CLINICAL_IMPRESSION_ID_PREFIX)
        else cif_impression_id
    )
    return _resolve_clinical_impression_id(key)


__all__ = [
    "CLINICAL_IMPRESSION_ID_PREFIX",
    "_bb_clinical_impressions",
]


def _bb_clinical_impressions(ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one ClinicalImpression per entry in extensions['clinical_impressions']."""
    ext = _o(ctx.record, "extensions", {}) or {}
    impressions = _o(ext, "clinical_impressions", []) or []
    if not impressions:
        return []
    return [_build_clinical_impression(imp, ctx.patient_id, ctx.country) for imp in impressions]


def _build_clinical_impression(imp: Any, patient_id: str, country: str = "US") -> dict[str, Any]:
    """Build one FHIR R4 ClinicalImpression from a ClinicalImpressionRecord.

    Issue #360 G4 (iris4h-ai 2026-07-22 feedback): JP output picks the
    Japanese description populated at document/engine.py side. The
    ``description_ja`` field is populated in parallel with ``description``
    (English) because ClinicalImpressionRecord does not carry the source
    parameters (day / los / phase / disease_id / severity) needed to
    re-derive the template at FHIR emission time — CIF must carry both
    strings, sibling to ``EncounterConditionProtocol.chief_complaint_ja``.
    """
    impression_id = _o(imp, "impression_id", "") or ""
    encounter_id = _o(imp, "encounter_id", "") or ""
    date_val = _o(imp, "date", None)
    description_en = _o(imp, "description", "") or ""
    description_ja = _o(imp, "description_ja", "") or ""
    description = description_ja if is_jp(country) and description_ja else description_en
    summary = _o(imp, "summary", "") or ""
    investigation_refs = _o(imp, "investigation_refs", []) or []
    finding_refs = _o(imp, "finding_refs", []) or []
    prognosis = _o(imp, "prognosis", "") or ""
    practitioner_id = _o(imp, "practitioner_id", "") or ""

    # date → ISO string (FP-UNIFY-2)
    effective_dt = to_fhir_datetime(date_val)

    # AD-32 snapshot semantics: the last day of an in-progress encounter is "in-progress".
    # All prior days (and all days of completed encounters) are "completed".
    is_in_progress = _o(imp, "is_in_progress", False)
    # Issue #854 Bucket B (PR-clinical-impression): opaque CI.id.
    # Structural key = pre-#854 id body (with `ci-` prefix stripped).
    _ci_structural_key = (
        impression_id.removeprefix(CLINICAL_IMPRESSION_ID_PREFIX)
        if impression_id.startswith(CLINICAL_IMPRESSION_ID_PREFIX)
        else impression_id
    )
    res: dict[str, Any] = {
        "resourceType": "ClinicalImpression",
        "id": _resolve_clinical_impression_id(_ci_structural_key),
        "identifier": [wrap_as_identifier(_ci_structural_key, CLINICAL_IMPRESSION_KEY_SYSTEM)],
        "status": "in-progress" if is_in_progress else "completed",
        "subject": {"reference": f"Patient/{patient_id}"},
    }

    if encounter_id:
        res["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    if effective_dt:
        res["effectiveDateTime"] = effective_dt

    # session-88j P1-12: LOINC visit-type code (34117-2 admission H&P /
    # 11506-3 progress note / 18842-5 discharge summary). Populated by
    # document/engine.py per encounter phase. If absent, `code` is
    # omitted (backwards-compatible with pre-P1-12 CIF records).
    code_loinc = _o(imp, "code_loinc", "") or ""
    code_loinc_display = _o(imp, "code_loinc_display", "") or ""
    if code_loinc:
        code_dict: dict[str, Any] = {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": code_loinc,
                    **({"display": code_loinc_display} if code_loinc_display else {}),
                }
            ],
        }
        if code_loinc_display:
            code_dict["text"] = code_loinc_display
        res["code"] = code_dict

    if description:
        res["description"] = description
    if summary:
        res["summary"] = summary
    if practitioner_id:
        res["assessor"] = {"reference": f"Practitioner/{practitioner_id}"}

    # investigation: group observation refs into a single investigation item
    if investigation_refs:
        res["investigation"] = [
            {
                "code": {"text": "Investigations"},
                "item": [{"reference": f"Observation/{ref}"} for ref in investigation_refs],
            }
        ]

    # finding: one entry per condition ref
    if finding_refs:
        res["finding"] = [{"itemReference": {"reference": f"Condition/{ref}"}} for ref in finding_refs]

    if prognosis:
        res["prognosisCodeableConcept"] = [{"text": prognosis}]

    return res
