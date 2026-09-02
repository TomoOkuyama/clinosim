"""Composition FHIR R4 builder (Tier 1 #3 α-min-1 Task 9, extended α-min-2 Task 12,
refactored to two-layer CIF in AD-65 Task 4).

Reads CIF record.documents where format_type='composition'. Emits one
Composition resource per matching ClinicalDocument. Section structure is
derived from doc["narrative"]["sections"] (dict[section_title, section_text])
— the flat ClinicalDocument.sections field was removed in AD-65 Task 1; the
narrative subtree is merged in by CIFReader (Task 4) before builders run.
A stub whose narrative is still None (Stage 2 narrative pass hasn't run for
this doc yet) is skipped with a warning rather than emitting an empty
Composition.

α-min-1 COMPOSITION doc types (Task 9):
  ADMISSION_HP (LOINC 34117-2), DISCHARGE_SUMMARY (LOINC 18842-5)

α-min-2 COMPOSITION doc types (Task 12 — automatically dispatched via format_type
string match; no engine code changes required):
  ADMISSION_NURSING_ASSESSMENT (LOINC 78390-2)
  NURSING_DISCHARGE_SUMMARY    (LOINC 34745-0)
  OUTPATIENT_SOAP              (LOINC 34131-3)
  ED_NOTE                      (LOINC 34878-9)

Section rendering (doc["narrative"]["sections"] dict → Composition.section[])
is otherwise unchanged; TemplateNarrativeGenerator (Task 6 α-min-1 + Task 8
α-min-2, invoked by TemplateNarrativePass Task 3) is the source of sections
dict content.

JP section.title locale mapping is deferred to β-JP-1 per α-min-1 adv-1 Lens 3
I-3 TODO (section titles remain as English snake_case keys).

No-drop invariant (CIF → FHIR):
  document_id         -> Composition.id (comp- prefix)
  loinc_code          -> Composition.type.coding[LOINC]
  encounter_id        -> Composition.encounter
  patient_id          -> Composition.subject
  author_practitioner_id -> Composition.author[]
  authored_datetime   -> Composition.date
  language            -> Composition.language
  narrative.sections  -> Composition.section[*] (title + text.div)

Canonical constant ownership:
- COMPOSITION_ID_PREFIX: clinosim.modules.document (writer-owner), imported here.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.document import COMPOSITION_ID_PREFIX, DOC_REFERENCE_ID_PREFIX
from clinosim.modules.document.narrative.registry import (
    resolve_section_loinc as _resolve_section_loinc,
)
from clinosim.modules.document.narrative.registry import (
    resolve_section_title as _resolve_section_title,
)
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.documents.referral_orgs import (
    build_external_org_resource,
    format_referral_destination_text,
    pick_external_hospital,
)
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref, resolve_encounter_id
from clinosim.modules.output.fhir_r4.lib.common import BundleContext, _escape_html, derive_meta_last_updated
from clinosim.modules.output.fhir_r4.lib.ids import derive_opaque_id

# === Issue #854 Bucket B (PR-composition): opaque Composition.id ===
# Same pattern as PR #357 / #863 / #867 / #868 / #869 / #878 / #879 /
# #880 / #881 / #882 / #883 / #884 / #885 / #886. Two Composition emit
# paths:
#   - general (this file, `_build_composition_generic`): structural key
#     = pre-#854 id body (`{enc_part}` where enc_part is the CIF-doc-id
#     body). Post-#854: `comp-<12hex>` (17 chars).
#   - radiology imgrpt (`documents/imaging_report.py`): structural key
#     = pre-#854 id body (`{enc}-imgrpt-{seq}`). Post-#854: same shape.
#
# Composition.identifier is 0..1 in FHIR R4 (single-cardinality) and JP-CLINS
# eDS/eReferral profiles fix its .system to
# `http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier`, so a
# separate structural-key identifier cannot be attached — the pre-#854 id
# body is not preserved on the resource. Callers needing round-trip must
# derive it deterministically via `_resolve_composition_id(enc_part)`.


def _resolve_composition_id(structural_key: str) -> str:
    """Return the opaque FHIR Composition.id from a structural key.

    Shape: ``comp-{sha256(structural_key)[:12]}`` = 17 chars, fixed.
    """
    return derive_opaque_id(COMPOSITION_ID_PREFIX, structural_key)


logger = logging.getLogger(__name__)

__all__ = [
    "COMPOSITION_ID_PREFIX",
    "_bb_compositions",
]

# #278:enc → free-text-doc-id 優先度用 LOINC 定数。
# module-scope(function 内では N806 lint violation)。
_HOSPITAL_COURSE_LOINC = "8648-8"
_PROGRESS_NOTE_LOINC = "11506-3"

# Issue #340:HL7 FHIR R4 core `clinicaldocument` profile canonical URL。
# module-scope 定数(function 内では N806 lint violation、また複数関数で参照)。
# spec 直接引用(feedback_verify_fhir_profile_uri_from_spec rule):
# `hl7.fhir.r4.core#4.0.1/package/StructureDefinition-clinicaldocument.json` の
# `url` field。JP-CLINS profile 未対応 LOINC の Composition 明示宣言に使用。
_CLINICALDOCUMENT_PROFILE = "http://hl7.org/fhir/StructureDefinition/clinicaldocument"


# Issue #819 (N-5): Practitioner staff-id regex — matches the canonical
# clinosim ID format `<ROLE-2>-<DEPT-2>-<NNN>` (e.g. `DR-CA-002`, `NS-OR-004`).
# Used by `_localize_practitioner_ids_in_text` to substitute raw IDs in
# narrative section text with the practitioner's real name + role suffix
# (looked up in `ctx.roster_map`).
_STAFF_ID_RE = re.compile(r"\b([A-Z]{2})-[A-Z]{2}-\d{3}\b")

# Role suffix map by staff-id prefix. Consumer narrative rendering guide:
# a Practitioner id prefix like `DR-*` renders with a "医師" suffix in JP
# and "physician" in EN; nurse ids (`NS-*` / `CN-*`) render with "看護師"
# etc. Prefixes not listed here render name-only (no suffix) so unknown
# staff roles do not silently fabricate a role.
_STAFF_ROLE_SUFFIX_JA: dict[str, str] = {
    "DR": "医師",
    "NS": "看護師",
    "CN": "看護師",  # certified nurse
    "RT": "呼吸療法士",
    "PT": "理学療法士",
    "OT": "作業療法士",
    "ST": "言語聴覚士",
    "PH": "薬剤師",
}
_STAFF_ROLE_SUFFIX_EN: dict[str, str] = {
    "DR": "physician",
    "NS": "nurse",
    "CN": "nurse",
    "RT": "respiratory therapist",
    "PT": "physical therapist",
    "OT": "occupational therapist",
    "ST": "speech therapist",
    "PH": "pharmacist",
}


def _localize_practitioner_ids_in_text(text: str, roster_map: dict[str, dict], country: str) -> str:
    """Substitute raw Practitioner staff ids (`DR-CA-002` etc.) with the
    practitioner's name + a role-suffix (`加瀬 幸男 医師`) using ``roster_map``.

    Idempotent when the same staff id appears multiple times in one text.
    Falls through unchanged for ids not found in ``roster_map`` — never
    fabricates a name for an unknown id. This is what fixes Issue #819
    (N-5): before this walker, narrative sections leaked raw ids into
    ``Composition.section[].text.div``.
    """
    if not text or not roster_map:
        return text
    suffix_map = _STAFF_ROLE_SUFFIX_JA if is_jp(country) else _STAFF_ROLE_SUFFIX_EN

    def _sub(m: re.Match) -> str:
        sid = m.group(0)
        prefix = m.group(1)
        staff = roster_map.get(sid) or {}
        name = staff.get("name") or ""
        if not name:
            return sid  # unknown → leave as-is
        suffix = suffix_map.get(prefix, "")
        if suffix:
            sep = "" if is_jp(country) else " "
            return f"{name}{sep}{suffix}" if is_jp(country) else f"{name} ({suffix})"
        return name

    return _STAFF_ID_RE.sub(_sub, text)


# =============================================================================
# Section catalog lookup (META #957 close-out session 97, 2026-09-02)
# =============================================================================
#
# Section slug metadata (title_ja / title_en / LOINC) previously lived in
# three parallel dicts here (`_SECTION_TITLE_JA`, `_SECTION_TITLE_EN`,
# `_SECTION_LOINC`). Asymmetric ship (e.g. PR #991 OPERATIVE_NOTE landing
# forgot the JA-side dict; raw slug `op_procedure_name` leaked as
# `Composition.section.title` on 36 JP p=500 sections, patched by PR #1055)
# proved the drift class was systemic.
#
# The three dicts are now consolidated into a single yaml SoT at
# `clinosim/modules/document/reference_data/section_catalog.yaml`, loaded +
# validated at import time via
# `clinosim.modules.document.narrative.registry.load_section_catalog` (fail-loud
# on any slug authored in `document_type_specs.yaml` that lacks a catalog
# entry). The two thin wrappers below preserve the historical call sites
# (`_localize_section_title` / `_SECTION_LOINC.get`) so grep/imports keep
# working while narrative CIF schema migration (Stage 2 title write-through)
# lands as a follow-up PR.
def _humanize_section_slug(slug: str) -> str:
    """Last-resort fallback humanization for a slug not registered in the
    catalog. `_validate_section_catalog` prevents this path from being hit
    for any slug authored in `document_type_specs.yaml`, but the helper is
    retained for safety on legacy fixture / ad-hoc callers that pass a
    non-registered title string. ``op_blood_loss`` → ``"Op blood loss"``.
    """
    if not slug:
        return slug
    return slug.replace("_", " ").capitalize()


def _localize_section_title(section_title: str, lang: str) -> str:
    """Return the display form of a `Composition.section.title` for `lang`.

    Reads from `section_catalog.yaml`. Unknown slugs (which should not
    happen for anything from `document_type_specs.yaml` — validated at
    import time) fall through to `_humanize_section_slug` on the US path
    or pass through unchanged on JP (matching pre-catalog behavior).
    """
    resolved = _resolve_section_title(section_title, lang)
    if resolved:
        return resolved
    if lang == "ja":
        return section_title  # JP path historically passed slug through on miss
    if section_title and (section_title[0].isupper() or " " in section_title):
        return section_title
    return _humanize_section_slug(section_title)


def _loinc_for_section(section_title: str) -> str | None:
    """Return the LOINC section code for `section_title`, or `None` if the
    slug is not registered in the catalog. Callers that previously used
    `_SECTION_LOINC.get(...)` now go through this helper."""
    code = _resolve_section_loinc(section_title)
    return code or None


# === Issue #925: encounter → linked-resource index ===
#
# Composition.section[].entry[] is meant to reference the underlying
# MedicationRequests / Observations / Procedures / Conditions that
# populate the section's narrative. At v0.5.0 all SOAP-note (34131-3)
# and discharge-summary (18842-5) section writers left `entry` unset,
# so document-first consumers had no structured navigation from a
# note to its prescriptions or labs (37,028 SOAP notes + 668 DS on
# the JP p=10000 snapshot). The fix populates entries at the emit
# site (same walk that writes `section.text.div` / `section.code`)
# from an encounter-scoped index of resources already emitted earlier
# in the bundle-builder pipeline.
#
# `RESOURCE_TYPES_INDEXED` is the fixed set of resource types the
# index captures — every type that a Composition section is likely to
# reference. New types can be added by extending this tuple; adding a
# type that never appears in `_SECTION_ENTRY_TYPES` (below) is dead
# work but not harmful. Kept as a module-scope tuple so the walker in
# ``_build_encounter_resource_index`` is O(1) per resource.
RESOURCE_TYPES_INDEXED = (
    "MedicationRequest",
    "Observation",
    "Procedure",
    "Condition",
    "ServiceRequest",
    "DiagnosticReport",
)


def _resource_display(resource: dict) -> str:
    """Return a short human-readable label for ``resource`` (for section.entry.display).

    Reads the fields most likely to carry a clinician-facing label —
    ``medicationCodeableConcept.text``, ``code.text``, first coding's
    ``display`` — falling back to the empty string when none is
    populated. The FHIR Reference.display element is 0..1 and purely
    advisory, so an empty return means the caller emits reference-only.
    """
    med = resource.get("medicationCodeableConcept")
    if isinstance(med, dict):
        text = med.get("text")
        if text:
            return str(text)
        codings = med.get("coding") or []
        if codings and isinstance(codings[0], dict):
            disp = codings[0].get("display")
            if disp:
                return str(disp)
    code = resource.get("code")
    if isinstance(code, dict):
        text = code.get("text")
        if text:
            return str(text)
        codings = code.get("coding") or []
        if codings and isinstance(codings[0], dict):
            disp = codings[0].get("display")
            if disp:
                return str(disp)
    return ""


def _build_encounter_resource_index(
    entries: list[dict[str, Any]],
) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Bucket already-emitted bundle entries by encounter and resourceType.

    Walks the bundle's accumulated entries list and returns
    ``{encounter_id: {resourceType: [Reference, ...], ...}, ...}``.
    Only resource types in :data:`RESOURCE_TYPES_INDEXED` are indexed;
    resources without an ``encounter.reference`` (or with an id that
    does not match the expected ``Encounter/<id>`` shape) are skipped.

    The returned Reference dicts are ready to drop into
    ``Composition.section[].entry[]``. When a resource carries a
    recognisable label, a ``display`` field is populated as a
    consumer hint (spec-optional).

    Callable independently for unit tests — a synthetic entries list
    yields a deterministic index without needing a full bundle build.
    """
    index: dict[str, dict[str, list[dict[str, str]]]] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        res = e.get("resource")
        if not isinstance(res, dict):
            continue
        rtype = res.get("resourceType")
        if rtype not in RESOURCE_TYPES_INDEXED:
            continue
        enc = res.get("encounter") or {}
        if not isinstance(enc, dict):
            continue
        ref = enc.get("reference", "")
        if not isinstance(ref, str) or not ref.startswith("Encounter/"):
            continue
        enc_id = ref[len("Encounter/") :]
        rid = res.get("id")
        if not rid:
            continue
        ref_entry: dict[str, str] = {"reference": f"{rtype}/{rid}"}
        disp = _resource_display(res)
        if disp:
            ref_entry["display"] = disp
        index.setdefault(enc_id, {}).setdefault(rtype, []).append(ref_entry)
    return index


# Section-title → resourceType[] mapping for
# ``_build_composition_generic`` (SOAP / admission H&P / ED note /
# nursing / rehab plan / …). Keys are the narrative section-title slugs
# authored by the template narrative pass (same keys as ``_SECTION_LOINC``
# below); values are the resourceType buckets whose entries belong in
# that section per FHIR/JP-CLINS/CCDA guidance. A section title not in
# this map emits no ``entry`` — the narrative-only sections (subjective /
# hpi / chief_complaint / present_illness / admission_reason) stay
# text-only, which is spec-clean (Composition.section.entry is 0..*).
#
# Rationale per bucket:
#  - plan / P: MedicationRequest (Rx written at the visit), ServiceRequest
#    (labs / imaging / referrals ordered), Procedure (in-visit or planned).
#  - assessment / A / diagnosis: Condition (the encounter's dx).
#  - objective / O / physical_exam / triage_details: Observation
#    (vitals, findings) + DiagnosticReport (labs interpreted here).
#  - discharge_medications: MedicationRequest (take-home Rx).
#  - medications_at_home: MedicationRequest (pre-visit / home Rx).
#  - hospital_course / admission_status: Procedure + Observation.
#  - ed_workup: ServiceRequest + Observation + DiagnosticReport.
_SECTION_ENTRY_TYPES: dict[str, tuple[str, ...]] = {
    # SOAP outpatient / progress notes
    "subjective": (),
    "objective": ("Observation", "DiagnosticReport"),
    "assessment": ("Condition",),
    "plan": ("MedicationRequest", "ServiceRequest", "Procedure"),
    # Admission H&P / progress
    "chief_complaint": (),
    "hpi": (),
    "past_medical_history": ("Condition",),
    "medications_at_home": ("MedicationRequest",),
    "physical_exam": ("Observation",),
    "physical_examination": ("Observation",),
    "triage_details": ("Observation",),
    # Discharge summary (US path — JP eDS uses `_JP_DS_SECTION_CODE`)
    "admission_summary": (),
    "hospital_course": ("Procedure", "Observation"),
    "discharge_diagnoses": ("Condition",),
    "discharge_medications": ("MedicationRequest",),
    "discharge_evaluation": ("Observation",),
    "discharge_readiness": ("Observation",),
    # Nursing / rehab
    "nursing_history": (),
    "nursing_diagnosis": ("Condition",),
    "nursing_interventions_provided": ("Procedure",),
    "admission_status": ("Observation",),
    "adl_assessment": ("Observation",),
    "risk_assessments": ("Observation",),
    "care_plan": ("MedicationRequest", "ServiceRequest", "Procedure"),
    # Ward-info & plan sections
    "diagnosis": ("Condition",),
    # ED / inpatient planning
    "ed_workup": ("ServiceRequest", "Observation", "DiagnosticReport"),
    "assessment_and_plan": ("Condition", "MedicationRequest", "ServiceRequest", "Procedure"),
    "treatment_plan": ("MedicationRequest", "ServiceRequest", "Procedure"),
    "test_schedule": ("ServiceRequest",),
    "surgery_schedule": ("Procedure", "ServiceRequest"),
    "other_plans": ("MedicationRequest", "ServiceRequest", "Procedure"),
    "follow_up": ("ServiceRequest",),
    "discharge_instructions": (),
    # Rehab
    "functional_status": ("Observation",),
    "basic_movement": ("Observation",),
    # Narrative-only remainder (kept explicit so a future author can see
    # the intent — an unknown key falls through to `()` via `.get(k, ())`).
}


def _derive_section_entries(
    section_title: str,
    encounter_id: str,
    encounter_index: dict[str, dict[str, list[dict[str, str]]]] | None,
) -> list[dict[str, str]]:
    """Return ``Composition.section[].entry[]`` for the generic builder.

    Filters the encounter-scoped index by the resource types associated
    with ``section_title`` in :data:`_SECTION_ENTRY_TYPES`. Returns an
    empty list (never ``[]`` on the resource) when there is no index,
    no encounter, or no resources of the eligible types — the caller
    then omits ``entry`` entirely so `Composition.section.entry` stays
    absent rather than emitting an empty array.

    ``encounter_id`` may be either a raw CIF encounter id (as carried
    on ``ClinicalDocument.encounter_id``) or the opaque post-#854
    ``enc-<12hex>`` form. The index is keyed on the OPAQUE form (built
    from ``resource.encounter.reference`` on already-emitted entries),
    so raw CIF ids are transformed via :func:`resolve_encounter_id`
    before the lookup. Passing a synthetic id that is already opaque
    round-trips through the resolver unchanged.
    """
    if not encounter_id or not encounter_index:
        return []
    types = _SECTION_ENTRY_TYPES.get(section_title, ())
    if not types:
        return []
    resolved_enc = resolve_encounter_id(encounter_id)
    # Fall back to the raw id when it matches directly (unit tests
    # frequently pass a synthetic literal like `"ENC-001"` and populate
    # the index with the same literal — the resolver would rewrite it
    # to an opaque form the test never saw).
    bucket = encounter_index.get(resolved_enc) or encounter_index.get(encounter_id) or {}
    out: list[dict[str, str]] = []
    for rtype in types:
        for ref in bucket.get(rtype, []):
            out.append(ref)
    return out


def _bb_compositions(ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one Composition per ClinicalDocument with format_type='composition'.

    Skips (with a warning) any stub whose narrative subtree is still None —
    i.e. the Stage 2 narrative pass has not (yet) generated content for this
    document_id. This is expected for documents produced between `generate`
    and `narrate` runs, not a data-quality defect.

    #278:pre-compute encounter_id → free-text DocumentReference
    id map so JP-CLINS eDS `hospitalCourseSection.entry` slice can point
    at a real per-encounter DocumentReference (e.g. progress note 11506-3
    from the same admission). Prefer LOINC 8648-8(Hospital course)/
    11506-3(Progress note)を優先、その他 free-text は fallback。
    """
    raw_docs = _o(ctx.record, "documents", []) or []
    lang = resolve_lang(ctx.country)

    # First pass: encounter_id → primary free-text doc id.
    # Priority: 8648-8 (Hospital course) > 11506-3 (Progress note) > any
    # other free-text doc from the same encounter (last-wins fallback).
    # LOINC constants live at module scope (`_HOSPITAL_COURSE_LOINC` /
    # `_PROGRESS_NOTE_LOINC`) — moved out of function body to satisfy
    # N806.
    # Issue #854 Bucket B (PR-document-reference): the values stored in
    # `enc_to_free_text` feed the `DocumentReference/{free_text_doc_id}`
    # template in section entries — they must be the OPAQUE DR ids the
    # writer emits, not the CIF-side compound. The intermediate `current`
    # comparisons still key on the CIF `doc.document_id` so priority
    # logic is unchanged; only the value written into the map is opaque.
    from clinosim.modules.output.fhir_r4.documents.documents import (
        document_reference_id_for_cif_doc_id,
    )

    enc_to_free_text: dict[str, str] = {}
    _enc_to_cif_doc_id: dict[str, str] = {}  # sidecar for priority comparison
    for doc in raw_docs:
        if _o(doc, "format_type", "") != "free_text":
            continue
        enc = _o(doc, "encounter_id", "") or ""
        doc_id = _o(doc, "document_id", "") or ""
        if not enc or not doc_id:
            continue
        loinc = _o(doc, "loinc_code", "") or ""
        current_cif = _enc_to_cif_doc_id.get(enc, "")
        opaque = document_reference_id_for_cif_doc_id(doc_id)
        # Prefer 8648-8 > 11506-3 > any; last-wins otherwise.
        if not current_cif:
            enc_to_free_text[enc] = opaque
            _enc_to_cif_doc_id[enc] = doc_id
        elif loinc == _HOSPITAL_COURSE_LOINC:
            enc_to_free_text[enc] = opaque
            _enc_to_cif_doc_id[enc] = doc_id
        # Only overwrite with 11506-3 if current is not already the higher-priority code.
        elif loinc == _PROGRESS_NOTE_LOINC:
            # Check if current is already 8648-8; look up its LOINC by matching CIF doc_id
            # in raw_docs. Cheap since we've already iterated once — small N per patient.
            current_loinc = ""
            for d2 in raw_docs:
                if _o(d2, "document_id", "") == current_cif:
                    current_loinc = _o(d2, "loinc_code", "") or ""
                    break
            if current_loinc != _HOSPITAL_COURSE_LOINC:
                enc_to_free_text[enc] = opaque
                _enc_to_cif_doc_id[enc] = doc_id

    # Pre-compute encounter_id → primary Condition id so JP-CLINS eDS
    # `diagnosesOnDischargeSection.entry` slice resolves to the correct
    # Condition. For chronic-primary encounters that resolves to
    # `cond-chronic-{patient}-{i:02d}` (the encounter-specific
    # `cond-{enc}-primary` is no longer emitted — session 88j Condition
    # dedup).
    from clinosim.modules.output.fhir_r4.conditions.primary_ref import primary_condition_ref

    enc_to_primary_cond: dict[str, str] = {}
    for _enc in ctx.record.get("encounters", []) or []:
        _eid = _o(_enc, "encounter_id", "") or ""
        if _eid:
            enc_to_primary_cond[_eid] = primary_condition_ref(ctx.record, ctx.patient_id, _eid)

    out: list[dict[str, Any]] = []
    # Issue #924: track the set of external Organizations sampled by any
    # emitted JP-CLINS referral letter (LOINC 57133-1) so we can emit them
    # alongside `Composition.ndjson` — the eReferral 910 slice
    # discriminator resolves against these Orgs at validation time. We
    # only emit those that are actually referenced (no orphans).
    external_org_ids_referenced: set[str] = set()
    # Issue #925: unit tests that fake `ctx` with a `types.SimpleNamespace`
    # (older test fixtures pre-dating this field) do not carry the
    # `encounter_resource_index` attribute — fall through to `None` so
    # those tests exercise the pre-#925 shape (sections without
    # `entry`). Production `BundleContext.encounter_resource_index`
    # defaults to `None` too, so this is a no-op on real calls.
    enc_index = getattr(ctx, "encounter_resource_index", None)
    for doc in raw_docs:
        if _o(doc, "format_type", "") != "composition":
            continue
        narrative = _o(doc, "narrative", None)
        if not narrative:
            logger.warning(
                "composition stub %s has no narrative (Stage 2 pass not run for this document) — skipping",
                _o(doc, "document_id", ""),
            )
            continue
        sections = _o(narrative, "sections", {}) or {}
        out.append(
            _build_composition(
                doc,
                sections,
                lang,
                enc_to_free_text,
                enc_to_primary_cond,
                roster_map=ctx.roster_map,
                encounter_index=enc_index,
            )
        )
        # Track sampled external org for referral letters (JP-only path).
        # Same seed (patient_id + encounter_id) as the builder, so the id
        # is byte-identical to the reference the builder wrote.
        if lang == "ja" and _o(doc, "loinc_code", "") == "57133-1":
            _pid = _o(doc, "patient_id", "") or ""
            _eid = _o(doc, "encounter_id", "") or ""
            _dest = pick_external_hospital(_pid, _eid, country="JP")
            if _dest:
                external_org_ids_referenced.add(_dest["id"])

    # Emit Organization resource per referenced external hospital. The
    # write() dedup helper in the adapter would fold duplicates anyway,
    # but resolving the catalog entries only for referenced ids keeps
    # ndjson from carrying orphan rows.
    if external_org_ids_referenced:
        from clinosim.locale.loader import load_external_organizations

        catalog_by_id = {e["id"]: e for e in load_external_organizations("JP")}
        for org_id in sorted(external_org_ids_referenced):
            entry = catalog_by_id.get(org_id)
            if entry is None:
                # Defensive — sampling always returns an entry from the
                # catalog, so this branch is unreachable in practice.
                continue
            out.append(build_external_org_resource(entry))
    return out


def _build_composition(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    enc_to_free_text: dict[str, str] | None = None,
    enc_to_primary_cond: dict[str, str] | None = None,
    *,
    roster_map: dict[str, dict] | None = None,
    encounter_index: dict[str, dict[str, list[dict[str, str]]]] | None = None,
) -> dict[str, Any]:
    """Build one FHIR R4 Composition resource from a ClinicalDocument + its sections.

    P2-13 PR2a: dispatches to the JP-CLINS-conformant builder when
    ``lang == "ja"`` and the LOINC code is 18842-5 (discharge summary).
    PR2b: 57133-1 (referral note) dispatches to the eReferral
    builder. Otherwise the existing generic builder is used (US path
    unchanged).

    Issue #925: ``encounter_index`` — the encounter-scoped resource
    bucket produced by :func:`_build_encounter_resource_index` — is
    threaded through so section writers can populate
    ``section.entry[]`` with references to the MedicationRequests /
    Observations / Procedures / Conditions belonging to this
    Composition's encounter. ``None`` when the caller has no index
    (unit tests calling the builder in isolation) — sections stay
    text-only.
    """
    task_type = _o(doc, "task_type", "")
    # Issue #961 extension: 死亡退院サマリー shares LOINC 18842-5 with the
    # generic discharge_summary but requires a distinct type.text / title
    # ("死亡退院サマリー" not "退院時サマリー") and does NOT conform to the
    # JP-CLINS eDS profile (its 8-section death-specific layout differs
    # from the eDS 10-section admission+discharge structure). Dispatch on
    # task_type FIRST so the shared LOINC does not route this to the
    # profile-strict eDS builder. This branch applies regardless of
    # locale — US path also benefits from the specialized title.
    if task_type == "death_discharge_summary":
        return _build_death_discharge_summary_composition(
            doc, sections, lang, roster_map=roster_map, encounter_index=encounter_index
        )
    if lang == "ja":
        loinc = _o(doc, "loinc_code", "")
        if loinc == "18842-5":
            return _build_jp_clins_discharge_summary_composition(
                doc,
                sections,
                lang,
                enc_to_free_text or {},
                enc_to_primary_cond or {},
                roster_map=roster_map,
                encounter_index=encounter_index,
            )
        if loinc == "57133-1":
            return _build_jp_clins_referral_note_composition(doc, sections, lang, roster_map=roster_map)
        # P2-13 PR3:JP-eCheckup General
        if loinc == "53576-5":
            return _build_jp_eCheckup_general_composition(doc, sections, lang, roster_map=roster_map)
        # Issue #961:死亡診断書 (Death certificate). Emit under jpfhir
        # doc-typecodes (per JP dispatch convention for JP-authored
        # documents) plus a CodeableConcept.text carrying 死亡診断書.
        if loinc == "64297-5":
            return _build_jp_death_certificate_composition(
                doc, sections, lang, roster_map=roster_map, encounter_index=encounter_index
            )
        # Issue #340:JP-CLINS profile が存在しない JP path
        # Composition (rehabilitation_plan LOINC 34823-5、admission_hp
        # 34117-2、ED / outpatient SOAP、nursing docs 等) に HL7 FHIR R4
        # core の `clinicaldocument` profile を meta.profile に明示宣言。
        #
        # Rationale (semantic + spec 準拠):
        #   - `http://hl7.org/fhir/StructureDefinition/clinicaldocument` は
        #     HL7 R4 core 公式 profile で Composition の refinement。
        #     baseDefinition = Composition、constraints:
        #       (1) Composition.subject targetProfile を Patient / Practitioner /
        #           Group / Device / Location に制限
        #       (2) versionNumber extension slice を宣言
        #   - clinosim の Composition は subject = Patient reference で emit
        #     (`_build_composition_generic` line 313)、targetProfile 完全準拠
        #   - 「これは clinical document」の semantic を国際 profile で宣言
        #     = base FHIR Composition profile 列挙のような redundant hack ではない
        #
        # Side effect: HAPI validator の VS 展開 default path 回避
        #   (v13 (2026-07-21) で HAPI 6.9.12 upgrade / okhttp3 化 / chunk 縮小 /
        #    Display cache patch 等 7 workaround 全滅した internal bug 対策、
        #    ただし profile 宣言自体は spec 準拠かつ意味的に honest)
        #
        # JP-CLINS eDS / eReferral / eCheckup の baseDefinition は Composition
        # 直下(clinicaldocument 経由でない)ため、それらの dispatch path は
        # 変更せず(既存 profile は追加の意味を提供済み)。
        comp = _build_composition_generic(doc, sections, lang, roster_map=roster_map, encounter_index=encounter_index)
        profs = comp.setdefault("meta", {}).setdefault("profile", [])
        if _CLINICALDOCUMENT_PROFILE not in profs:
            profs.append(_CLINICALDOCUMENT_PROFILE)
        return comp
    return _build_composition_generic(doc, sections, lang, roster_map=roster_map, encounter_index=encounter_index)


def _build_composition_generic(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    *,
    roster_map: dict[str, dict] | None = None,
    encounter_index: dict[str, dict[str, list[dict[str, str]]]] | None = None,
) -> dict[str, Any]:
    """Locale-neutral Composition builder — used by non-JP-CLINS paths.

    ``sections`` is the already-resolved ``doc["narrative"]["sections"]`` dict
    (extracted by ``_bb_compositions`` so this function stays narrative-shape
    agnostic and testable in isolation).

    Issue #819 (N-5): ``roster_map`` (from ``BundleContext.roster_map``) is
    used to substitute raw Practitioner staff-ids (``DR-CA-002`` etc.) in
    section text with the practitioner's real name + role suffix. When
    ``None`` (legacy callers / unit tests), section text is unchanged
    — same behavior as before this Issue.

    Issue #925: ``encounter_index`` — the encounter-scoped resource
    bucket produced by :func:`_build_encounter_resource_index` — is
    consulted in the same walk that emits ``section.title`` /
    ``section.code`` / ``section.text.div`` so ``section.entry[]``
    stays consistent with the narrative slotting (single-walk pattern
    per ``feedback_dr_conclusion_code_single_walk``). ``None`` (unit
    tests) means every section emits without ``entry`` — the previous
    behaviour, spec-clean under ``Composition.section.entry`` 0..*.
    """
    # Bind to a local so the inner `for section_title, section_text` loop
    # (added earlier) can reference `_roster_map` uniformly across the JP
    # eDS / eReferral / eCheckup variants that also call this function
    # via `_build_composition_generic(...)`.
    _roster_map = roster_map or {}
    loinc_code = _o(doc, "loinc_code", "")
    loinc_display = code_lookup("loinc", loinc_code, lang) if loinc_code else ""

    doc_id = _o(doc, "document_id", "")
    author_id = _o(doc, "author_practitioner_id", "")
    # FHIR R4 Composition.date 1..1 dateTime; empty string is invalid.
    # Sentinel "2000-01-01T00:00:00" matches engine.py:172 admission_dt fallback
    # so FHIR consumers see the same epoch value as the encounter.
    authored_dt = _o(doc, "authored_datetime", "") or "2000-01-01T00:00:00"
    patient_id = _o(doc, "patient_id", "")
    encounter_id = _o(doc, "encounter_id", "")
    language = _o(doc, "language", "en")

    # Strip DOC_REFERENCE_ID_PREFIX ("doc-") to obtain the structural key
    # (pre-#854 id body). Post-#854 the DR.id is opaque `doc-<12hex>`,
    # so stripping yields `<12hex>` — which is a valid structural-key
    # input. Post-#886 the DR.id ↔ Composition.id bridge stays stable
    # because both derivations funnel through their shared resolvers
    # from the same input.
    enc_part = doc_id[len(DOC_REFERENCE_ID_PREFIX) :] if doc_id.startswith(DOC_REFERENCE_ID_PREFIX) else doc_id
    # Issue #854 Bucket B (PR-composition): opaque Composition.id.
    comp_id = _resolve_composition_id(enc_part)
    _comp_structural_key = enc_part
    # C2-34: Composition.identifier (0..1) for cross-system
    # document tracking. (v4 §Composition.identifier URI):
    # JP-CLINS eDS / eReferral profiles fix `Composition.identifier.system`
    # to `http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier`
    # (StructureDefinition-JP-Composition-{eDS,eReferral}.json). US / generic
    # output keeps the clinosim namespace URI (no profile constraint). The
    # decision follows the caller's `lang` — JP-CLINS builders pass "ja",
    # generic / US pass "en".
    identifier_system = _JP_COMPOSITION_IDENTIFIER_SYSTEM if lang == "ja" else "urn:clinosim:composition-id"
    res: dict[str, Any] = {
        "resourceType": "Composition",
        "id": comp_id,
        "identifier": {
            "system": identifier_system,
            "value": comp_id,
        },
        "status": "final",
        "type": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": loinc_code,
                    "display": loinc_display or loinc_code,
                }
            ],
            "text": loinc_display or loinc_code,
        },
        "subject": patient_ref(patient_id),
        "date": authored_dt,
        # FHIR R4 Composition.author cardinality 1..*; empty [] is non-conformant.
        # Production fallback: encounter.attending_physician_id is populated to
        # FALLBACK_PHYSICIAN_ID (staff/engine.py) when the roster is empty, so
        # this branch should never fire in production. Placeholder surfaces
        # failures via reference integrity audit (dangling Practitioner/UNKNOWN)
        # rather than silently emitting [] (non-conformant) or hiding the bug.
        # TODO(Task 10/15): document enricher must always populate author_practitioner_id.
        "author": [{"reference": f"Practitioner/{author_id}"}]
        if author_id
        else [{"reference": "Practitioner/UNKNOWN"}],  # noqa: E501
        "title": loinc_display or loinc_code,
        # C5-27: Composition.confidentiality (0..1 code)
        # per HL7 CDA / FHIR ConfidentialityCode. `N` = Normal (default JP
        # 医療情報 practice). All clinical documents are Normal unless
        # explicit privacy tag is set.
        "confidentiality": "N",
        "language": language,
    }

    if encounter_id:
        res["encounter"] = encounter_ref(encounter_id)
        # CY7-11 (Chain-7): Composition.event — the clinical event(s) the
        # composition documents. For discharge summary / progress note /
        # H&P etc., this is the encounter the doc summarizes, with the
        # encounter period.
        _period_start = _o(doc, "period_start", "") or authored_dt
        _period_end = _o(doc, "period_end", "") or ""
        _event: dict[str, Any] = {"period": {}}
        if _period_start:
            _event["period"]["start"] = _period_start
        if _period_end:
            _event["period"]["end"] = _period_end
        _event["detail"] = [encounter_ref(encounter_id)]
        if _event["period"]:
            res["event"] = [_event]

    # CY7-12 (Chain-7): Composition.custodian — managing hospital.
    res["custodian"] = {"reference": "Organization/hospital-main"}

    # C3-02: Composition.attester — JP EHR legal
    # signature (電子署名). Attester = the document author (attending
    # physician) with mode=legal. FHIR R4 Composition.attester is 0..*;
    # populate when author_practitioner_id is known.
    if author_id and author_id != "UNKNOWN":
        res["attester"] = [
            {
                "mode": "legal",
                "time": authored_dt,
                "party": {"reference": f"Practitioner/{author_id}"},
            }
        ]

    # Build section[] from doc["narrative"]["sections"] (passed in as `sections`)
    # C2-27: resolve LOINC section codes from the
    # canonical mapping. Sections with a known LOINC code get `section.code`
    # populated for interop; unknown titles retain title-only (documented
    # deferral).
    section_entries: list[dict[str, Any]] = []
    # Issue #360 G3 (2026-07-22): resolve doc language once outside the loop
    # so title/code both see the same locale. Falls back to "en" for legacy
    # docs where the language field is unset.
    _doc_lang = _o(doc, "language", "") or "en"
    for section_title, section_text in sections.items():
        # Issue #819 (N-5): resolve raw Practitioner staff ids to real
        # names before HTML-escaping the section text. See
        # `_localize_practitioner_ids_in_text` docstring; idempotent
        # for unknown ids. Country is derived from doc lang: "ja" → "jp",
        # everything else → "us" (US path is FHIR-standard EN suffix).
        _country_for_names = "jp" if _doc_lang == "ja" else "us"
        _resolved_text = _localize_practitioner_ids_in_text(section_text, _roster_map or {}, _country_for_names)
        entry: dict[str, Any] = {
            "title": _localize_section_title(section_title, _doc_lang),
            "text": {
                "status": "generated",
                "div": f"<div xmlns='http://www.w3.org/1999/xhtml'>{_escape_html(_resolved_text)}</div>",
            },
        }
        loinc_section = _loinc_for_section(section_title)
        if loinc_section:
            _loinc_disp = code_lookup("loinc", loinc_section, _doc_lang) or section_title
            # p=500 review finding (session 89): LOINC is on the
            # English-only-CS list, so `_strip_japanese_display_on_english_only_systems`
            # post-processes `coding.display` away when it contains JP
            # characters. Without a sibling `text`, JP consumers lose the
            # human-readable section-code label entirely (bare code
            # survives, but that is not user-facing). Populate `.text`
            # with the same localized display so the dual-slot pattern
            # (coding.display=EN-canonical-or-stripped + text=locale)
            # holds. See feedback_dual_slot_english_only_cs.
            entry["code"] = {
                "coding": [
                    {
                        "system": get_system_uri("loinc"),
                        "code": loinc_section,
                        "display": _loinc_disp,
                    }
                ],
                "text": _loinc_disp,
            }
        # Issue #925: populate `section.entry[]` in the SAME walk that
        # writes `section.text.div` (single-walk pattern per
        # `feedback_dr_conclusion_code_single_walk`). Empty list means
        # this section has no eligible resources in the index — omit
        # `entry` rather than emitting `entry: []` so the spec-optional
        # cardinality stays absent (FHIR R4 `Composition.section.entry`
        # is 0..*; an empty array is legal but noisy).
        _section_entry_refs = _derive_section_entries(
            section_title,
            encounter_id,
            encounter_index,
        )
        if _section_entry_refs:
            entry["entry"] = _section_entry_refs
        section_entries.append(entry)
    if section_entries:
        res["section"] = section_entries

    return res


# ============================================================
# P2-13 PR2a:JP-CLINS 退院時サマリー用 Composition builder
# ============================================================

_JP_CLINS_DS_PROFILE = "http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/JP_Composition_eDischargeSummary"
_JPFHIR_DOC_TYPECODES_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"

# JP-CLINS eDS / eReferral pin
# `Composition.identifier.system` to this URI (spec `fixedUri`, verified via
# `clinical-information-sharing#1.13.0/package/StructureDefinition-JP-Composition-
# {eDischargeSummary,eReferral}.json`). Same URI as identifier
# slices on Observation / Condition / AI / MR.
_JP_COMPOSITION_IDENTIFIER_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"

# JP-CLINS eDS Composition required elements.
# Extension URL for `Composition.extension:version` (spec `fixedUri` on the
# slice discriminator). Verified via `clinical-information-sharing#1.13.0/
# package/StructureDefinition-JP-Composition-eDischargeSummary.json`.
_JP_EDS_VERSION_EXTENSION_URL = "http://hl7.org/fhir/StructureDefinition/composition-clinicaldocument-versionNumber"
# `Composition.category.coding` fixed system + fixed code per spec.
# doc-subtypecodes CS authoritative display (spec:
# `clinical-information-sharing#1.13.0/package/CodeSystem-jp-codeSystem-
# documentSubTypeCode.json`) → DISCHARGE = "退院時文書"。旧値 "退院時サマリー"
# は jpfhir-doc-typecodes CS(下記 `_JP_EDS_TYPE_DISPLAY_JA`)の display で
# あり、doc-subtypecodes CS とは別軸。 (#267) で 1 定数を
# 兼用したため drift、v5 validation で 126+126 errors として顕在化(#279)。
_JPFHIR_DOC_SUBTYPECODES_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-subtypecodes"
_JP_EDS_CATEGORY_CODE = "DISCHARGE"
_JP_EDS_CATEGORY_DISPLAY_JA = "退院時文書"
# jpfhir-doc-typecodes CS 18842-5 の JP display(`code_lookup` fallback +
# `Composition.title` に流用)。code_lookup が YAML から取得できる限り使わ
# れないが、YAML 破損時の safety net。
_JP_EDS_TYPE_DISPLAY_JA = "退院時サマリー"
# Section title-vs-display split (also used by Chain #8's eDS/eReferral
# builders; consolidated here for module scope).
_JP_SECTION_TITLE_SUFFIX = "セクション"


def _section_title_from_section_display(display: str) -> str:
    """Return the JP-CLINS `section.title` form for a section display —
    strip trailing `セクション` (spec `title.fixedString` / `patternString`
    is the short form; `code.coding.display.patternString` is long).
    Non-JP inputs pass through unchanged.
    """
    if isinstance(display, str) and display.endswith(_JP_SECTION_TITLE_SUFFIX):
        return display[: -len(_JP_SECTION_TITLE_SUFFIX)]
    return display


# JP-CLINS 実 canonical URL は
# `.../CodeSystem/document-section`(resource id `jp-codeSystem-clins-
# document-section` を path に含めない)。iris4h-ai の
# clinical-information-sharing#1.13.0/package/
# CodeSystem-jp-codeSystem-clins-document-section.json `.url` fixedUri
# を直接引用。従来の id-in-URL 版は HAPI で 1272 warn。
_JPFHIR_DOC_SECTION_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/document-section"

# JP-CLINS 退院時サマリー section キー → jpfhir-doc-section 番号 code.
# expanded from 5 admission-side to 10 required slices
# (5 admission + 5 discharge) so `Composition.section:structuredSection.section`
# min=10 is satisfied AND every required child slice (hospitalCourseSection,
# detailsOnDischargeSection, diagnosesOnDischargeSection,
# medicationOnDischargeSection, instructionOnDischargeSection) is present.
#
# Section-key names are the narrative-sections dict keys that
# `TemplateNarrativeGenerator` (Task 6 α-min-1 / Task 8 α-min-2) emits into
# `doc["narrative"]["sections"]`. When a discharge section key is absent
# on a specific ClinicalDocument (older narrative pass version), the builder
# emits the slice with an empty div — the slice is present with min=1 which
# is what the spec requires; per-slice `text` content is optional.
_JP_DS_SECTION_CODE: dict[str, str] = {
    # Admission side (5 slices — spec `patternString` for title)
    "admission_reason": "312",  # reasonForAdmissionSection / 入院理由
    "admission_details": "322",  # detailsOnAdmissionSection / 入院時詳細
    "admission_diagnoses": "342",  # diagnosesOnAdmissionSection / 入院時診断
    "chief_complaint": "352",  # chiefComplaintsSection / 主訴
    "present_illness": "360",  # presentIllnessSection / 現病歴
    # Discharge side (5 slices — additions)
    # #286: sections dict の key を `medication_on_discharge` /
    # `instruction_on_discharge` から narrative generator の実キー
    # `discharge_medications` / `discharge_instructions` に修正。前者は
    # slice 名(medicationOnDischarge)を key にしたためだが narrative
    # pass 側は `_build_discharge_medications` /
    # `_build_discharge_instructions` を α-min-1 から流用しており key 名
    # が `discharge_medications` / `discharge_instructions`。key drift で
    # sections.get(...) が常に空になり FHIR R4 `txt-2` 違反 260+ 件。
    "hospital_course": "333",  # hospitalCourseSection / 入院中経過
    "discharge_details": "324",  # detailsOnDischargeSection / 退院時詳細
    "discharge_diagnoses": "344",  # diagnosesOnDischargeSection / 退院時診断
    "discharge_medications": "444",  # medicationOnDischargeSection / 退院時投薬指示
    "discharge_instructions": "424",  # instructionOnDischargeSection / 退院時方針指示
}


# Follow-up (#267): section slices with a required `entry`
# reference. Values are `("resource_type", "id_template")`; the template
# receives `encounter_id` and `doc_id` (comp-prefixed) as keyword args and
# returns the reference string. The reference targets track the JP-CLINS spec
# `type.targetProfile` on each `.entry` element (verified against
# `clinical-information-sharing#1.13.0/package/StructureDefinition-JP-
# Composition-eDischargeSummary.json`).
# Issue #925: multi-ref extension to `_JP_DS_SECTION_ENTRY_REFERENCES`.
# Where the base map holds a single templated Reference per section
# (Encounter, Condition, DocumentReference), this map lets a section
# also pull every resource of a given resourceType from the encounter-
# scoped `BundleContext.encounter_resource_index`. The two are
# additive: if both apply on a section, the templated ref is emitted
# first and the multi-ref pass appends non-duplicate additions.
#
# Section-key rationale (per JP-CLINS eDS spec + issue #925):
#  - admission_diagnoses (342): Condition entries for the encounter
#    (empty in the base map; mirrors 344 for the primary Condition).
#  - discharge_diagnoses (344): additional Conditions beyond the
#    primary (comorbidities recorded at discharge).
#  - discharge_medications (444): every MedicationRequest on the
#    encounter (inpatient orders finished at discharge + discharge Rx).
#    Spec `medicationOnDischargeSection.entry` targetProfile is
#    JP_MedicationRequest_eCS, cardinality 0..* — safe to append.
#  - hospital_course (333) is INTENTIONALLY omitted from this map:
#    JP-CLINS eDS constrains `hospitalCourseSection.entry` to
#    JP_DocumentReference (a single free-text note); adding
#    Procedure/Observation there would violate the profile slicing.
_JP_DS_MULTI_ENTRY_TYPES: dict[str, tuple[str, ...]] = {
    "admission_diagnoses": ("Condition",),
    "discharge_diagnoses": ("Condition",),
    "discharge_medications": ("MedicationRequest",),
}


_JP_DS_SECTION_ENTRY_REFERENCES: dict[str, tuple[str, str]] = {
    # detailsOnAdmissionSection.entry min=1 max=1 → JP_Encounter
    "admission_details": ("Encounter", "Encounter/{encounter_id}"),
    # detailsOnDischargeSection.entry min=1 max=1 → JP_Encounter
    "discharge_details": ("Encounter", "Encounter/{encounter_id}"),
    # diagnosesOnDischargeSection.entry min=1 → JP_Condition (primary dx).
    # `{primary_cond_id}` is resolved by `_bb_compositions` via
    # `primary_condition_ref` so chronic-primary encounters point at the
    # patient-scoped chronic Condition instead of a suppressed
    # `cond-{enc}-primary` (session 88j Condition dedup).
    "discharge_diagnoses": ("Condition", "Condition/{primary_cond_id}"),
    # #278:hospitalCourseSection.entry min=1 → JP_DocumentReference
    # 同一 encounter の progress note(LOINC 11506-3)or hospital course
    # note(LOINC 8648-8)などの free-text DocumentReference id を precompute
    # で解決。id は `_bb_compositions` が構築する enc_to_free_text map から
    # `{free_text_doc_id}` として供給。map hit しない場合は never-fabricate
    # rule に従い entry を emit しない。
    "hospital_course": ("DocumentReference", "DocumentReference/{free_text_doc_id}"),
}


def _build_jp_clins_discharge_summary_composition(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    enc_to_free_text: dict[str, str] | None = None,
    enc_to_primary_cond: dict[str, str] | None = None,
    *,
    roster_map: dict[str, dict] | None = None,
    encounter_index: dict[str, dict[str, list[dict[str, str]]]] | None = None,
) -> dict[str, Any]:
    """JP-CLINS eDischargeSummary v1.13.0 準拠 Composition を emit する。

    汎用 Composition builder との差分:
      - meta.profile = [JP_Composition_eDischargeSummary]
      - type.coding[0].system = doc-typecodes(LOINC coding は US 互換の
        ため secondary として併存)
      - section は 1-level nested tree:300 構造情報 → 必須 5 子 section
        (312/322/342/352/360)。section.code.system は JP-CLINS 定義の
        document-section CodeSystem(URL:
        `http://jpfhir.jp/fhir/clins/CodeSystem/document-section`、LOINC
        section code ではない)。
    """
    # 共通 field(id / subject / date / author / encounter / attester /
    # custodian / confidentiality 等)は汎用 builder を再利用し、type と
    # section のみ上書きする。
    comp = _build_composition_generic(doc, sections, lang, roster_map=roster_map)

    # meta.profile 追加(既に含まれていれば skip)
    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _JP_CLINS_DS_PROFILE not in profs:
        profs.append(_JP_CLINS_DS_PROFILE)

    # (Chain #9) `meta.lastUpdated` min=1 — reuse authoredOn / date. Emit
    # only when a source datetime exists so we never fabricate.
    if not meta.get("lastUpdated"):
        ts = derive_meta_last_updated(comp, ("date",)) or _o(doc, "authored_datetime", "")
        if ts:
            meta["lastUpdated"] = ts

    # `type` field:jpfhir doc-typecodes を primary。
    # v3 fix: eDS profile constrains type.coding to max=1, so
    # emit only the doc-typecodes coding — the LOINC copy (previously
    # emitted for interop) violated the profile slicing on 129 resources.
    # The LOINC value is preserved via type.text so downstream consumers
    # can still recover the same code as text.
    disp = code_lookup("jpfhir-doc-typecodes", "18842-5", lang) or _JP_EDS_TYPE_DISPLAY_JA
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM, "code": "18842-5", "display": disp},
        ],
        "text": disp,
    }
    comp["title"] = disp

    # (Chain #9) `Composition.extension:version` min=1 — 文書バージョン番号。
    # The extension slice is discriminated by URL; value[x] is `valueString`
    # per spec `valueString`. clinosim emits "1" (initial issue) since no
    # revision history is tracked; downstream systems can update in place.
    exts = comp.setdefault("extension", [])
    if not any(isinstance(e, dict) and e.get("url") == _JP_EDS_VERSION_EXTENSION_URL for e in exts):
        exts.append({"url": _JP_EDS_VERSION_EXTENSION_URL, "valueString": "1"})

    # (Chain #9) `Composition.category` min=1 max=1 — fixed to DISCHARGE
    # under the doc-subtypecodes CodeSystem.
    comp["category"] = [
        {
            "coding": [
                {
                    "system": _JPFHIR_DOC_SUBTYPECODES_SYSTEM,
                    "code": _JP_EDS_CATEGORY_CODE,
                    "display": _JP_EDS_CATEGORY_DISPLAY_JA,
                }
            ]
        }
    ]

    # (Chain #9) `Composition.author` min=2 — 文書作成責任者 (Practitioner)
    # + 文書作成機関 (Organization). Generic builder already sets
    # author[0]=Practitioner from doc.author_practitioner_id. Append an
    # Organization reference.
    #
    # #330 eDS profile の Composition.author target は
    # JP_Organization_eCS 準拠を要求(spec verified)。Issue #746 の unify
    # 以後、`hospital-main` 自身が JP_Organization + JP_Organization_eCS を
    # 両宣言するため参照先を hospital-main に戻す(以前は
    # `hospital-main-ecs` 別 id を使う workaround で slice validation を
    # 通していたが、単一 org 案で自然解決)。
    authors = comp.setdefault("author", [])
    if not isinstance(authors, list):
        authors = []
        comp["author"] = authors
    if not any(isinstance(a, dict) and str(a.get("reference", "")).startswith("Organization/") for a in authors):
        authors.append({"reference": "Organization/hospital-main"})

    # #330 eDS profile の Composition.custodian target は
    # JP_Organization_eCS 準拠を要求。unify 済 hospital-main を参照。
    comp["custodian"] = {"reference": "Organization/hospital-main"}

    # (Chain #9) section tree — 300 parent + 10 required child sections.
    # yaml carries `構造情報セクション` (long form, matches spec `patternString`);
    # `_section_title_from_section_display` derives the short-form title
    # per spec `title.fixedString` (Chain #8 pattern).
    parent_disp = code_lookup("jpfhir-doc-section", "300", lang) or "構造情報セクション"
    parent_title = _section_title_from_section_display(parent_disp)
    # Chain #9 follow-up (#267): pre-compute the ids the
    # entry references need. hospital_course の deferral を
    # 解消 — `_bb_compositions` が enc → free-text DocumentReference id map
    # を precompute し `enc_to_free_text` として渡す。map hit しない場合は
    # `free_text_doc_id` を空文字で埋め、下の never-fabricate guard で drop。
    _enc_id = _o(doc, "encounter_id", "") or ""
    _free_text_doc_id = (enc_to_free_text or {}).get(_enc_id, "")
    # Fall back to the encounter-scoped opaque Condition.id when no map
    # was passed (unit tests exercise the builder directly). The real
    # caller (`_bb_compositions`) always supplies the map so chronic-
    # primary encounters resolve to the patient-scoped chronic Condition.
    # Issue #854 Bucket B (PR-condition): route through the shared
    # resolver so this reference stays byte-consistent with the emit.
    from clinosim.modules.output.fhir_r4.conditions.primary_ref import encounter_primary_condition_id

    _primary_cond_id = ""
    if enc_to_primary_cond:
        _primary_cond_id = enc_to_primary_cond.get(_enc_id, "")
    if not _primary_cond_id and _enc_id:
        _fallback_patient_id = _o(doc, "patient_id", "") or ""
        _primary_cond_id = encounter_primary_condition_id(_fallback_patient_id, _enc_id)
    # Issue #854 PR-encounter: template needs opaque encounter id.
    _entry_ctx = {
        "encounter_id": resolve_encounter_id(_enc_id) if _enc_id else "",
        "free_text_doc_id": _free_text_doc_id,
        "primary_cond_id": _primary_cond_id,
    }

    child_sections: list[dict[str, Any]] = []
    for key, code in _JP_DS_SECTION_CODE.items():
        disp_c = code_lookup("jpfhir-doc-section", code, lang) or key
        title_c = _section_title_from_section_display(disp_c)
        text_val = sections.get(key, "") or ""
        # Chain #9: section.code.text max=0 — drop `text` from `code`.
        section_obj: dict[str, Any] = {
            "title": title_c,
            "code": {
                "coding": [
                    {
                        "system": _JPFHIR_DOC_SECTION_SYSTEM,
                        "code": code,
                        "display": disp_c,
                    }
                ],
            },
            # Chain 8: JP-CLINS pins `text.status` to `additional`.
            "text": {
                "status": "additional",
                "div": (f'<div xmlns="http://www.w3.org/1999/xhtml">{_escape_html(text_val)}</div>'),
            },
        }
        # Chain #9 follow-up (#267): required `.entry` reference on
        # detailsOnAdmission / hospitalCourse / detailsOnDischarge /
        # diagnosesOnDischarge slices. Only emit when the referenced resource
        # id is derivable (encounter_id / document_id present); a missing
        # source leaves the entry off so we never fabricate a broken
        # reference.
        entry_spec = _JP_DS_SECTION_ENTRY_REFERENCES.get(key)
        if entry_spec is not None:
            _, ref_template = entry_spec
            try:
                ref = ref_template.format(**_entry_ctx)
            except KeyError:
                ref = ""
            # Reject broken references — any format substitution that ended up
            # empty leaves the string looking like `Encounter/` or
            # `Condition/cond--primary`. Both are dead references so we drop
            # the entry rather than emit garbage.
            # #278:`DocumentReference/` (empty free_text_doc_id
            # fallback) too — same never-fabricate guard.
            if ref.endswith("/") or "//" in ref or "cond--primary" in ref:
                ref = ""
            if ref:
                section_obj["entry"] = [{"reference": ref}]
        # Issue #925: extend the eDS section entries beyond the fixed
        # single-ref slices in `_JP_DS_SECTION_ENTRY_REFERENCES`.
        # `_JP_DS_MULTI_ENTRY_TYPES` maps a section key to the
        # resourceType bucket in `encounter_resource_index`; when the
        # bucket has entries we append them (avoiding the primary
        # Condition ref already emitted above so 344 does not double).
        # 342 (admission_diagnoses) mirrors 344's primary Condition
        # when the eDS has no separately-tracked admission Condition
        # resource — clinosim's `clinical_diagnosis` typically carries
        # a single primary shared by admission and discharge.
        _multi_types = _JP_DS_MULTI_ENTRY_TYPES.get(key, ())
        if _multi_types and encounter_index is not None and _enc_id:
            _existing_refs = {e.get("reference") for e in section_obj.get("entry", [])}
            # The index is keyed on OPAQUE encounter ids (built from
            # `resource.encounter.reference`); `_enc_id` here is the
            # raw CIF encounter id. Look up under the opaque form
            # first, with a fall-through to the raw id so unit tests
            # that pre-key the index with the raw id still resolve.
            _resolved_enc = resolve_encounter_id(_enc_id)
            _bucket = encounter_index.get(_resolved_enc) or encounter_index.get(_enc_id) or {}
            _extra: list[dict[str, str]] = []
            for _rtype in _multi_types:
                for _ref_entry in _bucket.get(_rtype, []):
                    if _ref_entry.get("reference") in _existing_refs:
                        continue
                    _extra.append(_ref_entry)
                    _existing_refs.add(_ref_entry.get("reference"))
            if _extra:
                section_obj.setdefault("entry", []).extend(_extra)
        # 342 (入院時診断) mirrors 344 primary Condition when the index
        # is not consulted (unit tests) — keeps parity between
        # admission/discharge dx sections so a document-first consumer
        # sees a Condition on both slices instead of only 344.
        if key == "admission_diagnoses" and "entry" not in section_obj and _primary_cond_id:
            section_obj["entry"] = [{"reference": f"Condition/{_primary_cond_id}"}]
        child_sections.append(section_obj)
    # Parent structuredSection — Chain #9: drop `code.text` (max=0) and use
    # title-short / display-long split.
    comp["section"] = [
        {
            "title": parent_title,
            "code": {
                "coding": [
                    {
                        "system": _JPFHIR_DOC_SECTION_SYSTEM,
                        "code": "300",
                        "display": parent_disp,
                    }
                ],
            },
            "section": child_sections,
        }
    ]
    return comp


# ============================================================
# P2-13 PR2b:JP-CLINS 診療情報提供書用 Composition builder
# ============================================================

_JP_CLINS_REFERRAL_PROFILE = "http://jpfhir.jp/fhir/eReferral/StructureDefinition/JP_Composition_eReferral"

# JP-CLINS eReferral の必須 section 構造:
#   920 紹介元 / 910 紹介先 / 300 構造情報
#     └ 950 紹介目的 / 340 傷病名・主訴 / 360 現病歴
# トップレベルは 920 + 910 を並列に配置、300 構造情報の下に 3 個の
# 子 section(950/340/360)を nest する。
# section キー → jpfhir 番号 code の対応:
_JP_REFERRAL_TOP_LEVEL: dict[str, str] = {
    "referring_institution": "920",
    "referral_destination": "910",
}
_JP_REFERRAL_STRUCTURAL_CHILDREN: dict[str, str] = {
    "referral_purpose": "950",
    "diagnoses_and_complaint": "340",
    "present_illness_ref": "360",
}

# #296:JP-CLINS eReferral の 920(紹介元)/ 910(紹介先)
# top-level section slice に必須の Organization reference。
#
# Issue #924 (2026-08-29): 以前は両 section entry を module-scope 定数
# `Organization/hospital-main` で pin していたため、100 % の referral
# letter が 紹介元 == 紹介先 == 当院 の self-loop になっていた
# (narrative の `紹介先:他院` と矛盾)。修正:
#   - 920 (referralFromOrganization) はそのまま `Organization/hospital-main`
#     を pin — 当院からの outgoing referral として発火 (retrospective に
#     全 fire path は discharge 由来 = 100 % outgoing)。
#   - 910 (referralToOrganization) は
#     `clinosim/locale/jp/external_organizations.yaml` catalog から
#     `(patient_id, encounter_id)` sha256 modulo で sample した外部
#     Organization を参照 (RNG-neutral)。910 の entry / text は builder 内
#     で per-doc に組み立てる。
#
# module-scope 定数 (function 内では N806 lint violation) は 920 の
# self-pin だけ残る。
#
# #313 の origin: eReferral 920/910 section entry slice は
# discriminator (type: profile, path: resolve()) で `JP_Organization_eCS`
# profile 準拠の Organization を要求する。以前は eCS 別 id
# `hospital-main-ecs` を追加 emit して参照していたが、Issue #746 で
# `hospital-main` 自身が JP_Organization + JP_Organization_eCS を両宣言
# するよう unify 済 — resolve() 後の profile 集合に eCS が含まれるため
# slice validation は成立する。Issue #924 で追加する外部 Organization
# 群も同 2 profile を declare する (referral_orgs.build_external_org_resource)。
_JP_ER_REFERRING_FROM_REF: list[dict[str, str]] = [{"reference": "Organization/hospital-main"}]


# #289 sibling of eDS Chain #9:JP-CLINS eReferral は eDS と同
# 5 top-level 制約を持つ(extension:version min=1 / category min=1 /
# author min=2 / meta.lastUpdated min=1 / event.code min=1)。CONSULT
# は authoritative doc-subtypecodes CS "他科コンサルト"(spec:
# clinical-information-sharing#1.13.0/package/CodeSystem-jp-codeSystem-
# documentSubTypeCode.json)。
_JP_ER_CATEGORY_CODE = "CONSULT"
_JP_ER_CATEGORY_DISPLAY_JA = "他科コンサルト"
# #309 event.code.text は権威 spec の fixedString。
# StructureDefinition-JP-Composition-eReferral.json:
#   Composition.event.code.text.fixedString = "診療情報提供書発行"
#   Composition.event.code.coding max=0(coding 禁止、text-only)
_JP_ER_EVENT_CODE_TEXT_JA = "診療情報提供書発行"


def _build_jp_clins_referral_note_composition(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    *,
    roster_map: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """JP-CLINS eReferral v1.13.0 準拠 Composition を emit する。

    汎用 Composition builder との差分:
      - meta.profile = [JP_Composition_eReferral]
      - type.coding[0].system = doc-typecodes(LOINC coding は interop 用に
        secondary として併存)
      - section は 2-level tree:
          top-level:920 紹介元, 910 紹介先, 300 構造情報
          300 の下:950 紹介目的, 340 傷病名・主訴, 360 現病歴
        section.code.system は JP-CLINS document-section CodeSystem
        (URL: `http://jpfhir.jp/fhir/clins/CodeSystem/document-section`)固定。
      - #289:eDS Chain #9 の 5 top-level 制約を eReferral にも適用。
    """
    comp = _build_composition_generic(doc, sections, lang, roster_map=roster_map)

    # meta.profile 追加(既に含まれていれば skip)
    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _JP_CLINS_REFERRAL_PROFILE not in profs:
        profs.append(_JP_CLINS_REFERRAL_PROFILE)

    # #289:meta.lastUpdated min=1(Chain #9 pattern)。builder-set 済なら尊重、
    # 未 set なら authored_datetime へ fallback。
    if not meta.get("lastUpdated"):
        ts = _o(doc, "authored_datetime", "")
        if ts:
            meta["lastUpdated"] = ts

    # `type` field:57133-1 (eReferral / referral note)
    # v3 fix: eReferral profile constrains type.coding to a
    # single doc-typecodes coding. LOINC copy removed; the LOINC value is
    # preserved via type.text.
    disp = code_lookup("jpfhir-doc-typecodes", "57133-1", lang) or "診療情報提供書"
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM, "code": "57133-1", "display": disp},
        ],
        "text": disp,
    }
    comp["title"] = disp

    # #289 (Chain #9 pattern):Composition.extension:version min=1。
    # 文書 revision 番号は未 tracking のため "1"(initial issue)を pin。
    exts = comp.setdefault("extension", [])
    if not any(isinstance(e, dict) and e.get("url") == _JP_EDS_VERSION_EXTENSION_URL for e in exts):
        exts.append({"url": _JP_EDS_VERSION_EXTENSION_URL, "valueString": "1"})

    # #289 (Chain #9 pattern):Composition.category min=1 max=1 — fixed to
    # CONSULT("他科コンサルト")under doc-subtypecodes CS(authoritative
    # display verified in spec CodeSystem file)。
    comp["category"] = [
        {
            "coding": [
                {
                    "system": _JPFHIR_DOC_SUBTYPECODES_SYSTEM,
                    "code": _JP_ER_CATEGORY_CODE,
                    "display": _JP_ER_CATEGORY_DISPLAY_JA,
                }
            ]
        }
    ]

    # #289 (Chain #9 pattern):Composition.author min=2 — 文書作成責任者
    # (Practitioner)+ 文書作成機関(Organization)。generic builder は既に
    # Practitioner を author[0] に置くので Organization reference を追加。
    #
    # #330 eReferral profile の Composition.author target は
    # JP_Organization_eCS 準拠を要求(spec verified)。Issue #746 の unify
    # 以後、`hospital-main` 自身が JP_Organization + JP_Organization_eCS を
    # 両宣言するため参照先を hospital-main に戻す。
    authors = comp.setdefault("author", [])
    if not isinstance(authors, list):
        authors = []
        comp["author"] = authors
    if not any(isinstance(a, dict) and str(a.get("reference", "")).startswith("Organization/") for a in authors):
        authors.append({"reference": "Organization/hospital-main"})

    # #330 eReferral profile の Composition.custodian target
    # も JP_Organization_eCS 準拠を要求(spec verified)。unify 済
    # hospital-main を参照。
    comp["custodian"] = {"reference": "Organization/hospital-main"}

    # #289:Composition.event.code min=1(coding は不要、text で満たす)。
    # generic builder が既に event[0]{period,detail} を set 済のため、既存
    # event[0] に code を追加。event 未 set の場合も安全に追加。
    # #309 code は Array 必須(FHIR JSON serialization、base
    # `Composition.event.code` cardinality `0..*`。profile は max=1 で
    # 制限するが JSON は依然 Array 表現)。v6 で 15 件 structure error
    # "プロパティcode は JSON 配列でなければならず、an Object ではありません"
    # の regression fix。
    events = comp.setdefault("event", [])
    if not events:
        events.append({})
    events[0].setdefault(
        "code",
        [{"text": _JP_ER_EVENT_CODE_TEXT_JA}],
    )

    # #296:`_one_section` に entry_refs 引数を追加し、920 /
    # 910 top-level slice に referralFrom/ToOrganization reference を渡す。
    def _one_section(
        section_code: str,
        text_val: str,
        entry_refs: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        # title = short form, display = long form.
        # `code.text` max=0 → omit.
        disp_c = code_lookup("jpfhir-doc-section", section_code, lang) or section_code
        title_c = _section_title_from_section_display(disp_c)
        section_obj: dict[str, Any] = {
            "title": title_c,
            "code": {
                "coding": [
                    {
                        "system": _JPFHIR_DOC_SECTION_SYSTEM,
                        "code": section_code,
                        "display": disp_c,
                    }
                ],
            },
            # Chain 8 (v2 feedback §【中優先 8】): JP-CLINS eReferral
            # pins Composition.section[*].text.status to fixedCode "additional".
            "text": {
                "status": "additional",
                "div": (f'<div xmlns="http://www.w3.org/1999/xhtml">{_escape_html(text_val)}</div>'),
            },
        }
        # JP-CLINS eReferral は 920 / 910 の 2 section に
        # `entry:referralFromOrganization` / `entry:referralToOrganization`
        # slice(それぞれ min=1)を要求。clinosim は referring destination
        # の別 Organization を model していないので、referralFrom = 自院
        # (hospital-main)、referralTo も自院を placeholder として emit
        # する(reference integrity は保たれる;data-shape trade-off)。
        if entry_refs:
            section_obj["entry"] = entry_refs
        return section_obj

    # Issue #924: 920 (referralFromOrganization) は当院 pin、910
    # (referralToOrganization) は外部カタログから
    # (patient_id, encounter_id) → sha256 modulo で decisions される
    # 外部 Organization を参照。narrative text も、`他院` placeholder
    # ではなく実際の facility name を含む sentence で上書き。
    # catalog 空 (US 等、`external_organizations.yaml` 未配置) の場合は
    # 従来通り hospital-main を pin (safety fallback) — self-loop 復活を
    # 覚悟した上での明示的 fallback。
    pid = _o(doc, "patient_id", "") or ""
    eid = _o(doc, "encounter_id", "") or ""
    external_dest = pick_external_hospital(pid, eid, country="JP") if lang == "ja" else None

    top_entry_by_code: dict[str, list[dict[str, str]]] = {
        "920": _JP_ER_REFERRING_FROM_REF,
        "910": ([{"reference": f"Organization/{external_dest['id']}"}] if external_dest else _JP_ER_REFERRING_FROM_REF),
    }
    top_text_by_key: dict[str, str] = {
        "referring_institution": sections.get("referring_institution", "") or "",
        "referral_destination": (
            format_referral_destination_text(external_dest, lang="ja")
            if external_dest
            else (sections.get("referral_destination", "") or "")
        ),
    }
    top_sections: list[dict[str, Any]] = []
    for key, code in _JP_REFERRAL_TOP_LEVEL.items():
        top_sections.append(_one_section(code, top_text_by_key.get(key, ""), top_entry_by_code.get(code)))

    # 300 structural, nesting 950 / 340 / 360
    struct_children: list[dict[str, Any]] = []
    for key, code in _JP_REFERRAL_STRUCTURAL_CHILDREN.items():
        struct_children.append(_one_section(code, sections.get(key, "") or ""))
    # yaml carries the canonical long form; title is derived by stripping
    # `セクション`; `code.text` is dropped (max=0 per spec).
    struct_parent_disp = code_lookup("jpfhir-doc-section", "300", lang) or "構造情報セクション"
    struct_parent_title = _section_title_from_section_display(struct_parent_disp)
    top_sections.append(
        {
            "title": struct_parent_title,
            "code": {
                "coding": [
                    {
                        "system": _JPFHIR_DOC_SECTION_SYSTEM,
                        "code": "300",
                        "display": struct_parent_disp,
                    }
                ],
            },
            "section": struct_children,
        }
    )
    comp["section"] = top_sections
    return comp


# ============================================================
# P2-13 PR3:JP-eCheckup General 健診結果報告書用 Composition builder
# ============================================================

_JP_ECHECKUP_GENERAL_PROFILE = "http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Composition_eCheckupGeneral"
_JPFHIR_ECHECKUP_SECTION_SYSTEM = "http://jpfhir.jp/fhir/eCheckup/CodeSystem/section-code"

# eCheckup General の section キー + 健診種別 → jpfhir eCheckup 番号 code(sub-PR-D)
# checkup_type("occupational"/"specific"/"regional_union")と section key
# (checkup_lab_results / checkup_questionnaire)の組で dispatch する。
_JP_ECHECKUP_SECTION_CODE_MATRIX: dict[str, dict[str, str]] = {
    "occupational": {
        "checkup_lab_results": "01031",  # 事業者健診検査結果セクション
        "checkup_questionnaire": "01032",  # 事業者健診問診結果セクション
    },
    "specific": {
        "checkup_lab_results": "01011",  # 特定健診検査結果セクション
        "checkup_questionnaire": "01012",  # 特定健診問診結果セクション
    },
    "regional_union": {
        "checkup_lab_results": "01021",  # 広域連合保健事業検査結果セクション
        "checkup_questionnaire": "01022",  # 広域連合保健事業問診結果セクション
    },
}

# 既存 test 互換 alias。checkup_type 未指定時は事業者健診として dispatch。
_JP_ECHECKUP_SECTION_CODE: dict[str, str] = _JP_ECHECKUP_SECTION_CODE_MATRIX["occupational"]


def _build_jp_eCheckup_general_composition(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    *,
    roster_map: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """JP-eCheckup General v1.7.0 準拠 Composition を emit する(JP-only、opt-in)。

    汎用 Composition builder との差分:
      - meta.profile = [JP_Composition_eCheckupGeneral]
      - type.coding[0].system = doc-typecodes(53576-5)、LOINC coding も併存
      - section は flat 2 個(事業者健診の必須 2 section:01031 検査結果、
        01032 問診結果)。section.code.system は eCheckup 固有 CodeSystem。
    """
    comp = _build_composition_generic(doc, sections, lang, roster_map=roster_map)

    # meta.profile 追加
    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _JP_ECHECKUP_GENERAL_PROFILE not in profs:
        profs.append(_JP_ECHECKUP_GENERAL_PROFILE)

    # `type` field:53576-5 を doc-typecodes と LOINC 両方で emit
    disp = code_lookup("jpfhir-doc-typecodes", "53576-5", lang) or "検診・健診報告書"
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM, "code": "53576-5", "display": disp},
            {
                "system": get_system_uri("loinc"),
                "code": "53576-5",
                "display": code_lookup("loinc", "53576-5", lang) or disp,
            },
        ],
        "text": disp,
    }
    comp["title"] = disp

    # section:2 個 flat(nesting なし)
    # sub-PR-D:doc.checkup_type から健診種別を dispatch(未設定なら
    # occupational 事業者健診にfallback)
    checkup_type = _o(doc, "checkup_type", "") or "occupational"
    section_code_map = _JP_ECHECKUP_SECTION_CODE_MATRIX.get(
        checkup_type, _JP_ECHECKUP_SECTION_CODE_MATRIX["occupational"]
    )
    section_entries: list[dict[str, Any]] = []
    for key, code in section_code_map.items():
        disp_c = code_lookup("jpfhir-eCheckup-section", code, lang) or key
        text_val = sections.get(key, "") or ""
        # eCheckup section entries follow the same code.text=absent /
        # title-vs-display convention as eDS / eReferral.
        title_c = _section_title_from_section_display(disp_c)
        section_entries.append(
            {
                "title": title_c,
                "code": {
                    "coding": [
                        {
                            "system": _JPFHIR_ECHECKUP_SECTION_SYSTEM,
                            "code": code,
                            "display": disp_c,
                        }
                    ],
                },
                # Chain 8 (v2 feedback §【中優先 8】): JP-CLINS
                # eDischargeSummary / eReferral / eCheckup pin
                # Composition.section[*].text.status to fixedCode "additional"
                # (see fhir-jp-validator/tx-server-build/.../clinical-information-sharing#1.13.0
                # StructureDefinition-JP-Composition-*.json). generic
                # Composition (_build_composition_generic below) keeps
                # "generated" per base FHIR default.
                "text": {
                    "status": "additional",
                    "div": (f'<div xmlns="http://www.w3.org/1999/xhtml">{_escape_html(text_val)}</div>'),
                },
            }
        )
    comp["section"] = section_entries
    return comp


# ============================================================
# Issue #961: 死亡診断書 (Death certificate) Composition builder
# ============================================================
#
# 医師法第 20 条 mandates that the attending physician issue a 死亡診断書
# whenever certifying a patient's death. Prior to this issue, all
# 47/6389 deceased patients in the p=6389 JP dataset were emitted with
# only the generic 退院時サマリー (LOINC 18842-5) — the same Composition
# a living patient discharged home receives — so a consumer could not
# distinguish a death from a routine discharge by Composition.type alone.
#
# Design (never-replace, always-alongside): the death certificate fires
# in ADDITION to the discharge summary, not as a replacement. Both are
# clinically valid on a death encounter:
#   - 退院時サマリー drives billing / administrative discharge processing
#   - 死亡診断書 is the legal certificate of death (医師法第 20 条)
#
# For US locale the generic Composition builder is used (LOINC 64297-5
# directly on Composition.type.coding). For JP the coding is emitted
# under the JP-CLINS doc-typecodes CS (`jpfhir-doc-typecodes`) with the
# LOINC code value preserved — same pattern as JP-eCheckup's LOINC
# 53576-5 coding-under-JP-CS convention. JP-CLINS does NOT ship a
# StructureDefinition for a death-certificate Composition profile, so no
# `meta.profile` beyond the HL7 core `clinicaldocument` is asserted; that
# is honest (per feedback_profile_assertion_requires_data_completeness —
# do not assert a profile unless the data actually meets its slices).

_DEATH_CERT_TYPE_DISPLAY_JA = "死亡診断書"

# Issue #961 extension: 死亡退院サマリー (Death discharge summary) display.
# Shares LOINC 18842-5 with the generic discharge summary; the JP
# hospital-canonical title for the death variant is 死亡退院サマリー.
# English label mirrors the section-title bilingual convention used
# elsewhere in this file (e.g. _SECTION_TITLE_EN).
_DEATH_DISCHARGE_SUMMARY_TITLE_JA = "死亡退院サマリー"
_DEATH_DISCHARGE_SUMMARY_TITLE_EN = "Death discharge summary"


def _build_jp_death_certificate_composition(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    *,
    roster_map: dict[str, dict] | None = None,
    encounter_index: dict[str, dict[str, list[dict[str, str]]]] | None = None,
) -> dict[str, Any]:
    """JP 死亡診断書 (Death certificate) Composition builder — Issue #961.

    Differences from the generic builder:
      - `type.coding[0].system` = jpfhir doc-typecodes (matches how
        other JP-authored doc types dispatch under the JP CS)
      - `type.text` and `title` = 死亡診断書
      - `meta.profile` gains the HL7 core clinicaldocument profile
        (no JP-CLINS-specific StructureDefinition exists for this
        Composition type — see module comment)
    """
    comp = _build_composition_generic(doc, sections, lang, roster_map=roster_map, encounter_index=encounter_index)

    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _CLINICALDOCUMENT_PROFILE not in profs:
        profs.append(_CLINICALDOCUMENT_PROFILE)

    if not meta.get("lastUpdated"):
        ts = derive_meta_last_updated(comp, ("date",)) or _o(doc, "authored_datetime", "")
        if ts:
            meta["lastUpdated"] = ts

    # Type coding: JP doc-typecodes primary (parallel to eDS / eReferral
    # dispatch). `code_lookup` returns the localized display from yaml;
    # fallback to the hardcoded JP display when yaml lookup fails (yaml
    # is the source of truth per feedback_constants_live_in_external_config).
    disp = code_lookup("jpfhir-doc-typecodes", "64297-5", lang) or _DEATH_CERT_TYPE_DISPLAY_JA
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM, "code": "64297-5", "display": disp},
        ],
        # Dual-slot at emit site (feedback_dual_slot_at_emit_site_not_post_process):
        # `.text` carries the JP display so consumers reading the
        # CodeableConcept.text see 死亡診断書 even if a post-process walker
        # ever strips the JP display from a coding under an English-only CS.
        "text": disp,
    }
    comp["title"] = disp
    return comp


# ============================================================
# Issue #961 extension: 死亡退院サマリー Composition builder
# ============================================================
#
# Real JP hospital deceased-inpatient discharges use a specialized
# 死亡退院サマリー template, distinct from both the generic 退院時サマリー
# (which fires only on LIVING discharges after this change) and from the
# 死亡診断書 legal certificate (LOINC 64297-5, always emitted alongside).
# This builder shares LOINC 18842-5 with the generic discharge summary
# but overrides `type.text` / `title` to "死亡退院サマリー" so consumers
# can disambiguate death vs living discharge from the Composition title
# alone — the deployed cohort's 47/6389 deaths were previously buried
# under an ambulatory-style "退院時サマリー" title.
#
# We deliberately do NOT assert the JP-CLINS eDS profile:
#   1. The eDS profile enforces 10 admission+discharge sections; the
#      death variant has 8 different narrative sections
#      (admission_state / treatment_course / terminal_course /
#      circumstances_of_death / cause_of_death /
#      complications_and_comorbidities / family_communication /
#      autopsy_status_and_findings). Asserting the profile without
#      meeting its slices is a per-feedback_profile_assertion_requires_
#      data_completeness anti-pattern.
#   2. JP-CLINS does not ship a StructureDefinition for a death-variant
#      discharge summary; asserting eDS on this document would be a
#      false profile claim.
# The `clinicaldocument` HL7 core profile IS asserted (same treatment as
# the death certificate) so consumers can still discover this is a
# clinical document via meta.profile.


def _build_death_discharge_summary_composition(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    *,
    roster_map: dict[str, dict] | None = None,
    encounter_index: dict[str, dict[str, list[dict[str, str]]]] | None = None,
) -> dict[str, Any]:
    """Build the 死亡退院サマリー / Death discharge summary Composition — Issue #961 ext.

    Differences from the generic builder:
      - `type.text` and `title` are the death-variant labels (JP:
        死亡退院サマリー / EN: Death discharge summary), NOT the
        LOINC 18842-5 canonical display ("退院時サマリー" /
        "Discharge summary" — those are the LIVING-discharge labels).
      - JP path emits the coding under the JP doc-typecodes CS
        (parallel to the eDS / eReferral / eCheckup dispatch) so the
        JP consumer sees a JP-authored code system, with the LOINC
        code value preserved.
      - `meta.profile` adds the HL7 core `clinicaldocument` profile;
        JP-CLINS eDS is intentionally NOT asserted (section list
        differs — see module comment).
    """
    comp = _build_composition_generic(doc, sections, lang, roster_map=roster_map, encounter_index=encounter_index)

    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _CLINICALDOCUMENT_PROFILE not in profs:
        profs.append(_CLINICALDOCUMENT_PROFILE)

    if not meta.get("lastUpdated"):
        ts = derive_meta_last_updated(comp, ("date",)) or _o(doc, "authored_datetime", "")
        if ts:
            meta["lastUpdated"] = ts

    if lang == "ja":
        # Emit under jpfhir doc-typecodes with the death-variant title
        # (feedback_dual_slot_at_emit_site_not_post_process — set `.text`
        # here rather than rely on a post-process walker). The LOINC
        # code 18842-5 lives inside the JP CS coding to preserve
        # cross-system code lookup; only the display text changes.
        comp["type"] = {
            "coding": [
                {
                    "system": _JPFHIR_DOC_TYPECODES_SYSTEM,
                    "code": "18842-5",
                    "display": _DEATH_DISCHARGE_SUMMARY_TITLE_JA,
                },
            ],
            "text": _DEATH_DISCHARGE_SUMMARY_TITLE_JA,
        }
        comp["title"] = _DEATH_DISCHARGE_SUMMARY_TITLE_JA
    else:
        # US / EN path: keep the LOINC coding but override the human-
        # readable slots with the death-variant label.
        comp["type"] = {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": "18842-5",
                    "display": _DEATH_DISCHARGE_SUMMARY_TITLE_EN,
                },
            ],
            "text": _DEATH_DISCHARGE_SUMMARY_TITLE_EN,
        }
        comp["title"] = _DEATH_DISCHARGE_SUMMARY_TITLE_EN

    return comp
