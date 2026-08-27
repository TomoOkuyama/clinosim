"""Imaging report Composition builder (Issue #818 / N-4).

Emits a formal `Composition` resource per `RadiologyReport` (one per
`ImagingStudyRecord.report`) so consumers get a section-structured
radiology narrative document, not just the 1-line ``DR.conclusion`` and
free-text ``text.div``.

Composition shape (mirrors JP-CLINS eDS / eReferral layout):
- ``type``: LOINC ``18748-4`` "画像検査報告書" / "Diagnostic imaging study"
- ``category``: LOINC LP29684-5 (Radiology; JP-CLINS convention) +
  v2-0074 RAD (FHIR-standard consumer-query tag for
  ``Composition?category=RAD``)
- ``section``: 2 required sections rebuilt from the RadiologyReport
  template — "Findings" + "Impression" (localized per country). More
  sections (imaging technique, differential, follow-up recommendations)
  are deliberately not fabricated — the CIF does not carry those data.
- ``author``: RadiologyReport doesn't currently carry a reading-
  radiologist id, so the encounter attending physician is the fallback
  (see roster) — same fallback rule as the sibling radiology DR
  ``_build_radiology_dr``.

The Composition id follows the pattern
``comp-{encounter_id}-imgrpt-{n}`` — parallels the imaging DR's
``imgrpt-{encounter_id}-{n}`` prefix for easy cross-reference.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import is_jp
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref
from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (  # type: ignore[attr-defined]
    RADIOLOGY_CATEGORY_V2_0074,
    RADIOLOGY_REPORT_ID_PREFIX,
    V2_0074_SYSTEM,
)
from clinosim.modules.output.fhir_r4.lib.common import BundleContext, _escape_html, to_fhir_datetime

# LOINC "画像検査報告書" — the canonical Composition.type for radiology
# reports, verified via JP-CLINS eImaging / JP Core radiology profile.
_IMAGING_REPORT_LOINC = "18748-4"
_IMAGING_REPORT_TITLE_JA = "画像検査報告書"
_IMAGING_REPORT_TITLE_EN = "Diagnostic imaging study report"

# LOINC LP29684-5 "放射線" for category:first slice (JP-CLINS
# JP_DiagnosticReport_Radiology profile). Kept consistent with the
# sibling radiology DR emit so query filters return both together.
_LP29684_5_LOINC = "LP29684-5"
_LP29684_5_DISPLAY_JA = "放射線"
_LP29684_5_DISPLAY_EN = "Radiology"

# Section titles + LOINC codes. Only Findings + Impression are
# populated from the CIF; other sections (technique, differential,
# recommendations) are documented deferrals — the CIF does not carry
# them, and fabricating them violates the no-fabrication policy.
_SECTION_FINDINGS_LOINC = "18782-3"  # LOINC "Study observation"
_SECTION_IMPRESSION_LOINC = "19005-8"  # LOINC "Radiology imaging study impression"

# Issue #818 follow-up: id-shape must interleave with the other
# Composition ids (`comp-<encounter>-<seq>`) so that any consumer
# alphabetic-sort default-paginated query (`_count=500` etc.) returns a
# representative mix rather than 0 imgrpt records because
# `comp-imgrpt-…` sorts after every `comp-ENC-…`. Encounter goes first
# so all Compositions for one encounter cluster together in the sort;
# the trailing `imgrpt-<seq>` differentiates from the encounter's other
# document Compositions.
_COMPOSITION_ID_PATTERN = "comp-{encounter_id}-imgrpt-{seq}"

# JP-CLINS Composition profile — reuse the eDischargeSummary shape for
# `meta.profile` optional interop; not strictly required by JP-CLINS
# eImaging spec (which currently references only DR / ImagingStudy),
# so we leave it off by default and let downstream validators pin as
# needed.


def _build_imaging_report_composition(
    study: Any,
    report: Any,
    ctx: BundleContext,
    seq: str,
) -> dict[str, Any]:
    """Build one Composition resource for a single ImagingStudy + RadiologyReport.

    ``seq`` is passed as a string to match the ``imgrpt-<enc>-<n>`` DR id
    suffix — this keeps DR ↔ Composition id parity even when the sequence
    would produce a non-integer suffix (e.g. legacy `imgrpt-<enc>-a`).
    """
    country = ctx.country
    _is_jp = is_jp(country)

    encounter_id = _o(study, "encounter_id", "") or ""
    patient_id = _o(study, "patient_id", "") or ctx.patient_id
    started_dt = _o(study, "started_datetime", None)
    date_iso = to_fhir_datetime(started_dt) if started_dt else ""

    # Author: reader-radiologist not on report; fall back to the encounter's
    # attending physician via roster_map (mirrors radiology DR fallback).
    attending_id: str = ""
    for enc in ctx.record.get("encounters", []) or []:
        eid = _o(enc, "encounter_id", "")
        if eid == encounter_id:
            attending_id = _o(enc, "attending_physician_id", "") or ""
            break
    if not attending_id and ctx.roster_map:
        attending_id = next(
            (s.get("staff_id", "") for s in ctx.roster_map.values() if s.get("role") == "physician"),
            "",
        )

    findings_en = _o(report, "findings_text", "") or ""
    findings_ja = _o(report, "findings_text_ja", "") or ""
    impression_en = _o(report, "impression_text", "") or ""
    impression_ja = _o(report, "impression_text_ja", "") or ""
    findings = (findings_ja if _is_jp and findings_ja else findings_en) or ""
    impression = (impression_ja if _is_jp and impression_ja else impression_en) or ""

    sections: list[dict[str, Any]] = []
    # p=500 review finding (session 89): LOINC is on the English-only-CS
    # list, so `_strip_japanese_display_on_english_only_systems` strips
    # `coding.display` when JP. Populate `.text` on the CodeableConcept
    # so the dual-slot pattern (coding.display=EN-canonical-or-stripped
    # + text=locale) holds on the radiology imaging-report Composition
    # section codes too. See feedback_dual_slot_english_only_cs.
    if findings:
        _findings_disp = "所見" if _is_jp else "Study observation"
        sections.append(
            {
                "title": "所見" if _is_jp else "Findings",
                "code": {
                    "coding": [
                        {
                            "system": get_system_uri("loinc"),
                            "code": _SECTION_FINDINGS_LOINC,
                            "display": _findings_disp,
                        }
                    ],
                    "text": _findings_disp,
                },
                "text": {
                    "status": "generated",
                    "div": f"<div xmlns='http://www.w3.org/1999/xhtml'>{_escape_html(findings)}</div>",
                },
            }
        )
    if impression:
        _impression_disp = "印象" if _is_jp else "Radiology imaging study impression"
        sections.append(
            {
                "title": "印象" if _is_jp else "Impression",
                "code": {
                    "coding": [
                        {
                            "system": get_system_uri("loinc"),
                            "code": _SECTION_IMPRESSION_LOINC,
                            "display": _impression_disp,
                        }
                    ],
                    "text": _impression_disp,
                },
                "text": {
                    "status": "generated",
                    "div": f"<div xmlns='http://www.w3.org/1999/xhtml'>{_escape_html(impression)}</div>",
                },
            }
        )

    _title = _IMAGING_REPORT_TITLE_JA if _is_jp else _IMAGING_REPORT_TITLE_EN
    _lp_display = _LP29684_5_DISPLAY_JA if _is_jp else _LP29684_5_DISPLAY_EN

    # Issue #854 Bucket B (PR-composition): opaque Composition.id.
    # Structural key = pre-#854 id body (without `comp-` prefix) =
    # `{encounter_id}-imgrpt-{seq}`. The routed derivation ensures the
    # id stays byte-consistent with the shared resolver.
    from clinosim.modules.output.fhir_r4.documents.composition import _resolve_composition_id

    _comp_structural_key = f"{encounter_id}-imgrpt-{seq}"
    resource: dict[str, Any] = {
        "resourceType": "Composition",
        "id": _resolve_composition_id(_comp_structural_key),
        "status": "final",
        "type": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": _IMAGING_REPORT_LOINC,
                    "display": _title,
                }
            ],
            "text": _title,
        },
        # Issue #815 / #818 pattern: dual category (LOINC LP29684-5 for
        # JP-CLINS profile compliance; v2-0074 RAD for FHIR-standard
        # ?category=RAD query).
        "category": [
            {
                "coding": [
                    {
                        "system": get_system_uri("loinc"),
                        "code": _LP29684_5_LOINC,
                        "display": _lp_display,
                    }
                ]
            },
            {
                "coding": [
                    {
                        "system": V2_0074_SYSTEM,
                        "code": RADIOLOGY_CATEGORY_V2_0074,
                        "display": "Radiology",
                    }
                ]
            },
        ],
        "subject": patient_ref(patient_id),
        "title": _title,
    }
    if encounter_id:
        resource["encounter"] = encounter_ref(encounter_id)
    if date_iso:
        resource["date"] = date_iso
    if attending_id:
        resource["author"] = [{"reference": f"Practitioner/{attending_id}"}]
    if sections:
        resource["section"] = sections
    return resource


def _bb_imaging_report_compositions(ctx: BundleContext) -> list[dict[str, Any]]:
    """Bundle builder (AD-56): one Composition per RadiologyReport.

    Coexists with `_build_radiology_dr` (which emits the parallel
    `imgrpt-*` DiagnosticReport). Together they give consumers both a
    machine-friendly DR resource AND a section-structured Composition
    for narrative rendering.
    """
    out: list[dict[str, Any]] = []
    studies = (_o(ctx.record, "extensions", {}) or {}).get("imaging") or []
    for study in studies:
        report = _o(study, "report")
        if not report:
            continue
        # Reuse the imgrpt id suffix so DR & Composition ids line up.
        rep_id = _o(report, "report_id", "") or ""
        seq = "1"
        if rep_id.startswith(RADIOLOGY_REPORT_ID_PREFIX):
            trailing = rep_id[len(RADIOLOGY_REPORT_ID_PREFIX) :]
            parts = trailing.rsplit("-", 1)
            if len(parts) == 2:
                seq = parts[1]
        out.append(_build_imaging_report_composition(study, report, ctx, seq))
    return out
