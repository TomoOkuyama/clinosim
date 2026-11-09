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

from clinosim.codes import display as registry_display
from clinosim.codes import get_system_uri
from clinosim.countries import lang_for
from clinosim.locale.i18n import t
from clinosim.locale.localized import localized_field
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document import CLINICAL_IMPRESSION_ID_PREFIX
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.lib.common import display_entry
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.fhir_time import to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)
from clinosim.types.encounter import OrderType

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
    return [_build_clinical_impression(imp, ctx.patient_id, ctx.country, record=ctx.record) for imp in impressions]


def _day_abnormal_lab_idxs(record: dict, encounter_id: str, day: Any) -> list[int]:
    """Order-list indices of the lab results flagged abnormal on ``day``'s date."""
    from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _ABNORMAL_LAB_FLAGS

    day_str = str(to_fhir_datetime(day) or "")[:10]
    out: list[int] = []
    for idx, order in enumerate(record.get("orders") or []):
        if _o(order, "order_type") not in (OrderType.LAB, "lab"):
            continue
        if encounter_id and (_o(order, "encounter_id", "") or "") != encounter_id:
            continue
        result = _o(order, "result")
        if not result or _o(result, "value") is None:
            continue
        if str(_o(result, "flag") or "").upper() not in _ABNORMAL_LAB_FLAGS:
            continue
        if str(to_fhir_datetime(_o(result, "result_datetime")) or "")[:10] == day_str:
            out.append(idx)
    return out


def _build_clinical_impression(
    imp: Any, patient_id: str, country: str = "US", record: dict | None = None
) -> dict[str, Any]:
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
    description = localized_field(imp, "description", lang_for(country))
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
        "subject": patient_ref(patient_id),
    }

    if encounter_id:
        res["encounter"] = encounter_ref(encounter_id)
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
                    "system": get_system_uri("loinc"),
                    "code": code_loinc,
                    # Issue #3026: the coding keeps an English display (the
                    # CIF's when it is English, else the LOINC registry's);
                    # the CIF's localized name stays in text.
                    **display_entry(
                        (
                            code_loinc_display
                            if code_loinc_display.isascii()
                            else registry_display("loinc", code_loinc, "en") or ""
                        )
                        if code_loinc_display
                        else ""
                    ),
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

    # Issue #2652: the problem assessed (the encounter's primary diagnosis),
    # the day's abnormal lab results as findings, and a fact-only summary of
    # them (the panel-report conclusion format), when the CIF carries none.
    if record is not None and encounter_id:
        from clinosim.modules.output.fhir_r4.conditions.primary_ref import primary_condition_ref
        from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
            _build_lab_panel_conclusion,
            _GroupedPanel,
            lab_observation_id,
        )

        lang = lang_for(country)
        if record.get("clinical_diagnosis"):
            res["problem"] = [{"reference": f"Condition/{primary_condition_ref(record, patient_id, encounter_id)}"}]
        idxs = _day_abnormal_lab_idxs(record, encounter_id, date_val)
        if idxs and "finding" not in res:
            res["finding"] = [
                {"itemReference": {"reference": f"Observation/{lab_observation_id(encounter_id, i)}"}} for i in idxs
            ]
        if "summary" not in res:
            # One value per analyte (the day's latest), in order of first appearance.
            orders = record.get("orders") or []
            latest: dict[str, int] = {}
            for i in idxs:
                name = str(_o(_o(orders[i], "result"), "lab_name") or _o(orders[i], "display_name") or "")
                prev = latest.get(name)
                when = str(_o(_o(orders[i], "result"), "result_datetime") or "")
                if prev is None or when >= str(_o(_o(orders[prev], "result"), "result_datetime") or ""):
                    latest[name] = i
            group = _GroupedPanel(panel_name="", bucket="", obs_idxs=sorted(latest.values()))
            text, _abnormal = _build_lab_panel_conclusion(group, record.get("orders") or [], encounter_id, lang)
            res["summary"] = text or t("clinical_impression.no_abnormal_results", lang)

    return res
