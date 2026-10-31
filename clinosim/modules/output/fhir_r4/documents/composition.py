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
from functools import cache
from pathlib import Path
from typing import Any

from clinosim.codes import display as registry_display
from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import is_jp, resolve_lang, uses_jp_clins_profile
from clinosim.modules.document import COMPOSITION_ID_PREFIX, DOC_REFERENCE_ID_PREFIX
from clinosim.modules.document.narrative.registry import (
    resolve_section_loinc as _resolve_section_loinc,
)
from clinosim.modules.document.narrative.registry import (
    resolve_section_title as _resolve_section_title,
)
from clinosim.modules.output.fhir_r4.demographics.patient import patient_ref
from clinosim.modules.output.fhir_r4.documents.jp_clins.discharge_summary import (
    _build_jp_clins_discharge_summary_composition,
)
from clinosim.modules.output.fhir_r4.documents.jp_clins.echeckup_general import (
    _JP_ECHECKUP_GENERAL_PROFILE,  # noqa: F401 — re-exported for test / downstream use
    _JP_ECHECKUP_SECTION_CODE_MATRIX,  # noqa: F401 — re-exported for test / downstream use
    _JPFHIR_ECHECKUP_SECTION_SYSTEM,  # noqa: F401 — re-exported for test / downstream use
    _build_jp_echeckup_general_composition,
)
from clinosim.modules.output.fhir_r4.documents.jp_clins.referral_note import (
    _JP_CLINS_REFERRAL_PROFILE,  # noqa: F401 — re-exported for test / downstream use
    _JP_ER_CATEGORY_CODE,  # noqa: F401 — re-exported for test / downstream use
    _JP_ER_CATEGORY_DISPLAY_JA,  # noqa: F401 — re-exported for test / downstream use
    _JP_ER_EVENT_CODE_TEXT_JA,  # noqa: F401 — re-exported for test / downstream use
    _JP_ER_REFERRING_FROM_REF,  # noqa: F401 — re-exported for test / downstream use
    _JP_REFERRAL_STRUCTURAL_CHILDREN,  # noqa: F401 — re-exported for test / downstream use
    _JP_REFERRAL_TOP_LEVEL,  # noqa: F401 — re-exported for test / downstream use
    _build_jp_clins_referral_note_composition,
)
from clinosim.modules.output.fhir_r4.documents.referral_orgs import (
    build_external_org_resource,
    pick_external_hospital,
)
from clinosim.modules.output.fhir_r4.encounters.encounter import encounter_ref, resolve_encounter_id
from clinosim.modules.output.fhir_r4.lib.common import (
    BundleContext,
    _escape_html,
    derive_meta_last_updated,
    dual_slot_concept,
)
from clinosim.modules.output.fhir_r4.lib.ids import derive_opaque_id
from clinosim.modules.output.fhir_r4.lib.localization import _clinician_role_rows

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


# `_uses_jp_clins_profile` was introduced module-locally in Phase 1d-54
# and promoted to `clinosim.modules._shared.uses_jp_clins_profile` in
# Phase 1d-60 (see that module's docstring). Kept as a module alias so
# existing callsite spelling stays intact; new callers import the
# shared symbol directly.
_uses_jp_clins_profile = uses_jp_clins_profile


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
# Staff id-prefix → role-suffix maps are derived from
# `clinosim/codes/data/clinosim-clinician-role.yaml` (JP + EN columns on
# the same row). Call `_staff_role_suffix_ja()` / `_staff_role_suffix_en()`
# at the use site instead of a module-level constant.


def _staff_role_suffix_ja() -> dict[str, str]:
    out: dict[str, str] = {}
    for row in _clinician_role_rows().values():
        prefix = row.get("staff_prefix") if isinstance(row, dict) else None
        suffix = row.get("suffix_ja") if isinstance(row, dict) else None
        if isinstance(prefix, str) and isinstance(suffix, str):
            out[prefix] = suffix
    return out


def _staff_role_suffix_en() -> dict[str, str]:
    out: dict[str, str] = {}
    for row in _clinician_role_rows().values():
        prefix = row.get("staff_prefix") if isinstance(row, dict) else None
        suffix = row.get("suffix_en") if isinstance(row, dict) else None
        if isinstance(prefix, str) and isinstance(suffix, str):
            out[prefix] = suffix
    return out


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
    suffix_map = _staff_role_suffix_ja() if is_jp(country) else _staff_role_suffix_en()

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
#
# Full registry (plus per-section rationale and extension protocol)
# lives in `clinosim/codes/data/composition-section-entry-types.yaml`
# (hardcoded-review Phase A6). The alias below preserves the Python
# symbol name so every call site in `_derive_section_entries` stays
# unchanged; a section title not in the yaml falls through to the
# existing `.get(k, ())` default.


@cache
def _section_entry_types() -> dict[str, tuple[str, ...]]:
    """Load the Composition.section[].entry resource-type registry."""
    import yaml

    path = Path(__file__).resolve().parents[4] / "codes" / "data" / "composition-section-entry-types.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    out: dict[str, tuple[str, ...]] = {}
    for section, types in (raw.get("sections", {}) or {}).items():
        out[str(section)] = tuple(str(rt) for rt in (types or []))
    return out


_SECTION_ENTRY_TYPES: dict[str, tuple[str, ...]] = _section_entry_types()


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
        # Track sampled external org for referral letters (JP-CLINS
        # eReferral 57133-1 doc-type). Same seed (patient_id +
        # encounter_id) as the builder, so the id is byte-identical to
        # the reference the builder wrote.
        if _uses_jp_clins_profile(lang) and _o(doc, "loinc_code", "") == "57133-1":
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
    if _uses_jp_clins_profile(lang):
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
            return _build_jp_echeckup_general_composition(doc, sections, lang, roster_map=roster_map)
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
    # decision follows the caller's profile family (JP-CLINS builders pass
    # `lang="ja"`; generic / US pass `lang="en"`), routed through the
    # `_uses_jp_clins_profile` predicate so a future locale that should NOT
    # trigger the JP-CLINS URI can override the decision in one place.
    identifier_system = (
        _JP_COMPOSITION_IDENTIFIER_SYSTEM if _uses_jp_clins_profile(lang) else "urn:clinosim:composition-id"
    )
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
            _loinc_disp = registry_display("loinc", loinc_section, _doc_lang) or section_title
            # p=500 review finding (session 89): LOINC is on the
            # English-only-CS list, so `_strip_japanese_display_on_english_only_systems`
            # post-processes `coding.display` away when it contains JP
            # characters. Without a sibling `text`, JP consumers lose the
            # human-readable section-code label entirely (bare code
            # survives, but that is not user-facing). Populate `.text`
            # with the same localized display so the dual-slot pattern
            # (coding.display=EN-canonical-or-stripped + text=locale)
            # holds (AGENTS.md dual-slot convention).
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
_JPFHIR_DOC_TYPECODES_SYSTEM = get_system_uri("jpfhir-doc-typecodes")

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
_JPFHIR_DOC_SUBTYPECODES_SYSTEM = get_system_uri("jpfhir-doc-subtypecodes")
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
_JPFHIR_DOC_SECTION_SYSTEM = get_system_uri("jpfhir-doc-section")

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
# JP-CLINS eDS section registry moved to
# `clinosim/codes/data/jp-clins-eds-section-codes.yaml` under the
# post-#1880 review (hardcoded-audit Finding 10). The yaml carries code,
# title, multi_entry_types, and entry_ref per section in one row.


# JP-CLINS eDS section slice registry + the per-section helpers
# (_jp_ds_sections, _jp_ds_section_code, _jp_ds_multi_entry_types,
# _jp_ds_section_entry_references) moved to the JP-CLINS discharge-
# summary submodule as part of the full-review Phase B2 split; see
# `clinosim/modules/output/fhir_r4/documents/jp_clins/discharge_summary.py`.
# The yaml authority at `codes/data/jp-clins-eds-section-codes.yaml`
# is unchanged (hardcoded-audit Finding 10).

# _build_jp_clins_discharge_summary_composition moved to
#
# as part of the full-review Phase B2 split (CRITICAL C5a). Re-exported
# at module scope via the import at the top of this file so the
#  dispatcher import keeps working.

# _build_jp_clins_referral_note_composition moved to
# clinosim/modules/output/fhir_r4/documents/jp_clins/referral_note.py
# (full-review Phase B3, CRITICAL C5b).

# _build_jp_echeckup_general_composition moved to
# clinosim/modules/output/fhir_r4/documents/jp_clins/echeckup_general.py
# (full-review Phase B4, CRITICAL C5c).


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
    disp = registry_display("jpfhir-doc-typecodes", "64297-5", lang) or _DEATH_CERT_TYPE_DISPLAY_JA
    # Dual-slot at the emit site (Issue #2276): doc-typecodes is a JP
    # CodeSystem, so the coding keeps the Japanese display and `.text` carries
    # the same label.
    comp["type"] = dual_slot_concept("jpfhir-doc-typecodes", "64297-5", lang, text=disp, fallback_display=disp)
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

    if uses_jp_clins_profile(lang):
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
