"""N-3 fix: re-route ED-period child resources from IMP encounter to the
synthesized ``-ED`` bridge Encounter.

Background (CY7-05, 2026-07-11): when a CIF inpatient encounter has
``admit_source=EMD`` (admitted via emergency department), the FHIR adapter
synthesizes a minimal companion Encounter with id ``{IMP_id}-ED`` so the
``partOf`` reference on the IMP resolves. That bridge Encounter had zero
child resources — every ED-time document (救急科記録 / triage note) and
every ED-time observation was silently attached to the IMP Encounter,
losing the semantic distinction between "what happened in ED" and "what
happened during the inpatient stay".

This walker runs once per resource inside the bundle loop and rewrites
``resource.encounter.reference`` (and ``context.encounter[].reference``
for DocumentReference) from ``Encounter/{IMP_id}`` to
``Encounter/{IMP_id}-ED`` for resources that semantically belong to the
ED stay.

**Document trigger: doc_type.** Composition / DocumentReference whose
LOINC type code is 34878-9 (ED note, 救急科記録) or 54094-8 (ED triage note,
トリアージ記録) is attributed to the ED bridge.

**Vital-sign trigger: provenance** (Issue #3243). The ED arrival vital-sign
set the triage enricher records for a via-ED admission carries
``data_source == ED_TRIAGE_DATA_SOURCE``; its Observations (and the NEWS2 /
GCS scored from it) are emitted on the ED bridge through
:func:`vital_sign_encounter_id`, which the builders call when they emit.

**Why not timestamp:** an earlier draft added a timestamp-based fallback
(route resources whose effective date falls within the ED window before IMP
admission). Testing against the p=200 s800 baseline showed CIF timestamps
are unreliable proxies for semantic locus — nursing intake notes are stamped
at 08:00 (which happens to land in the ED window preceding an 08:37
admission) but are clinically ward activity, not ED activity. Routing them
to the -ED bridge would misrepresent the clinical narrative. Only explicit
provenance routes a resource.

Idempotent: only rewrites when the current reference matches the IMP id
exactly, so re-running the walker (or running it against already-attributed
data) does nothing.
"""

from __future__ import annotations

from typing import Any

from clinosim.modules._shared import ED_TRIAGE_DATA_SOURCE, admitted_via_ed, get_attr_or_key
from clinosim.modules.document.narrative.registry import document_loinc
from clinosim.modules.output.fhir_r4.encounters.encounter import resolve_encounter_id

# LOINC codes that semantically belong to the ED stay. Kept as a
# module-level constant so the two builders that emit these types
# (composition.py / documents.py) can import the same source of truth
# if they ever grow their own routing hooks.
ED_DOC_TYPE_LOINC: frozenset[str] = frozenset(
    {
        document_loinc("ed_note"),  # ED note (救急科記録)
        document_loinc("ed_triage_note"),  # ED triage note (トリアージ記録)
    }
)


def reattribute_encounter_to_ed_bridge(resource: dict, ctx: Any) -> None:
    """Rewrite ``resource.encounter.reference`` in-place when the resource
    is an ED-typed Composition / DocumentReference and the record's IMP
    encounter was admitted via ED.

    No-op when:
      - the primary IMP encounter was not admitted via ED (admit_source != emd)
      - the resource is not one of the ED doc types (LOINC 34878-9 / 54094-8)
      - the resource has no ``encounter`` / ``context.encounter[]`` reference
        that matches the IMP encounter id (already routed elsewhere —
        respect existing attribution)
    """
    imp_id = _resolve_ed_imp_id(ctx)
    if imp_id is None:
        return
    if not _is_ed_by_doc_type(resource):
        return

    # Issue #854 PR-encounter: cross-refs go through the shared resolver
    # so the "opaque id" invariant holds — the IMP structural key is the
    # CIF ``encounter_id``, the bridge structural key is ``{IMP_id}-ED``
    # (built at inline_bb.py:334 via ``_make_synth_ed_enc_dict``).
    imp_ref = f"Encounter/{resolve_encounter_id(imp_id)}"
    ed_ref = f"Encounter/{resolve_encounter_id(f'{imp_id}-ED')}"

    # Top-level `encounter.reference` (Composition, Observation, Procedure,
    # MedicationRequest, MedicationAdministration, DiagnosticReport,
    # ClinicalImpression, ImagingStudy, Condition, …).
    enc_ref = resource.get("encounter")
    if isinstance(enc_ref, dict) and enc_ref.get("reference") == imp_ref:
        enc_ref["reference"] = ed_ref

    # DocumentReference emits its encounter inside `context.encounter[]`
    # (an array of Reference) per the R4 spec. Rewrite in place.
    context = resource.get("context")
    if isinstance(context, dict):
        for ref in context.get("encounter") or []:
            if isinstance(ref, dict) and ref.get("reference") == imp_ref:
                ref["reference"] = ed_ref


def vital_sign_encounter_id(vs: Any, ctx: Any) -> str:
    """CIF encounter id a vital-sign set's Observations reference: the ED
    bridge ``{IMP}-ED`` for the ED arrival set of a via-ED admission
    (``data_source == ED_TRIAGE_DATA_SOURCE``, Issue #3243), else the
    record's primary encounter (``ctx.primary_enc_id``)."""
    if get_attr_or_key(vs, "data_source", "") == ED_TRIAGE_DATA_SOURCE:
        imp_id = _resolve_ed_imp_id(ctx)
        if imp_id is not None:
            return f"{imp_id}-ED"
    return str(getattr(ctx, "primary_enc_id", "") or "")


def _resolve_ed_imp_id(ctx: Any) -> str | None:
    """Return the IMP encounter id when the record has an ED-admitted
    (``admit_source == emd``) primary encounter; otherwise ``None``.
    Cached on ctx to avoid re-parsing per-resource.
    """
    cached = getattr(ctx, "_ed_imp_id_cache", None)
    if cached is not None:
        # Sentinel (False) = "already computed, no ED bridge applies".
        return cached if cached is not False else None

    imp_id: str | None = None
    encounters = ctx.record.get("encounters", []) if isinstance(ctx.record, dict) else []
    if encounters:
        imp = encounters[0]
        if admitted_via_ed(imp):
            raw = get_attr_or_key(imp, "encounter_id") or ""
            if raw:
                imp_id = str(raw)

    try:
        ctx._ed_imp_id_cache = imp_id if imp_id is not None else False  # noqa: SLF001
    except AttributeError:
        pass
    return imp_id


def _is_ed_by_doc_type(resource: dict) -> bool:
    rt = resource.get("resourceType")
    if rt not in ("Composition", "DocumentReference"):
        return False
    type_field = resource.get("type") or {}
    for coding in type_field.get("coding", []) or []:
        if coding.get("code") in ED_DOC_TYPE_LOINC:
            return True
    return False
