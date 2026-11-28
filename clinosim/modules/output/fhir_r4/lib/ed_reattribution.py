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

**Time trigger for orders, results, doses and procedures** (Issue #3672).
A resource earlier than an Encounter's start is not part of that Encounter.
Observation, ServiceRequest, DiagnosticReport, MedicationRequest,
MedicationAdministration and Procedure whose own clinical time falls in the
ED window ``[admission - admitted_ed_stay(), admission)`` of a via-ED
admission are routed to the bridge by :func:`reattribute_ed_phase_by_time`
(no CIF flag, no RNG). The clinical time is the resource's own time (a lab
drawn in the ED and resulted after admission goes to the ED), not its
issue / result time.

The ImagingStudy is routed by its ``started`` time, and the imaging-report
Composition (LOINC 18748-4) by the start of the ImagingStudy it describes (its
own ``date`` is the report time, after the study). A MedicationAdministration
carries its Encounter in ``context`` (Issue #3866).

**Why other documents stay type-routed:** an earlier draft routed documents by
timestamp too. Testing against the p=200 s800 baseline showed CIF timestamps
are unreliable proxies for the locus of a *document* — nursing intake notes
are stamped at 08:00 (which happens to land in the ED window preceding an
08:37 admission) but are clinically ward activity, not ED activity. So
Composition / DocumentReference keep their doc-type routing only (imaging
reports excepted, above).

Idempotent: only rewrites when the current reference matches the IMP id
exactly, so re-running the walker (or running it against already-attributed
data) does nothing.
"""

from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules._shared import ED_TRIAGE_DATA_SOURCE, admitted_via_ed, get_attr_or_key
from clinosim.modules.document.narrative.registry import document_loinc
from clinosim.modules.output.fhir_r4.encounters.encounter import resolve_encounter_id
from clinosim.modules.triage.engine import admitted_ed_stay

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
    (``data_source == ED_TRIAGE_DATA_SOURCE``, Issue #3243); else, when the
    set was taken outside the primary encounter's period, the record's other
    outpatient encounter (the companion vaccination visit) whose period
    holds its timestamp (Issue #3656); else the record's primary encounter
    (``ctx.primary_enc_id``)."""
    if get_attr_or_key(vs, "data_source", "") == ED_TRIAGE_DATA_SOURCE:
        imp_id = _resolve_ed_imp_id(ctx)
        if imp_id is not None:
            return f"{imp_id}-ED"
    primary = str(getattr(ctx, "primary_enc_id", "") or "")
    at = _as_datetime(get_attr_or_key(vs, "timestamp", None))
    record = getattr(ctx, "record", None)
    encounters = record.get("encounters", []) if isinstance(record, dict) else []
    if at is None or not encounters:
        return primary
    held: list[str] = []
    for enc in encounters:
        eid = str(get_attr_or_key(enc, "encounter_id", "") or "")
        start = _as_datetime(get_attr_or_key(enc, "admission_datetime", None))
        end = _as_datetime(get_attr_or_key(enc, "discharge_datetime", None))
        if not eid or start is None or end is None or not start <= at <= end:
            continue
        if eid == primary:
            return primary
        etype = str(get_attr_or_key(enc, "encounter_type", "") or "").lower()
        if etype in ("outpatient", "amb", "ambulatory"):
            held.append(eid)
    return held[0] if held else primary


def vital_sign_encounter_end(vs: Any, ctx: Any) -> datetime | None:
    """End of the Encounter a vital-sign set's Observations reference
    (Issue #3959): the end of the ED window for the ED bridge, else the
    discharge time of the CIF encounter :func:`vital_sign_encounter_id` names;
    ``None`` when that encounter has no end (the offsets are left alone)."""
    eid = vital_sign_encounter_id(vs, ctx)
    imp_id = _resolve_ed_imp_id(ctx)
    if imp_id is not None and eid == f"{imp_id}-ED":
        window = _ed_window(ctx)
        return window[1] if window is not None else None
    record = getattr(ctx, "record", None)
    for enc in record.get("encounters", []) if isinstance(record, dict) else []:
        if str(get_attr_or_key(enc, "encounter_id", "") or "") == eid:
            return _as_datetime(get_attr_or_key(enc, "discharge_datetime", None))
    return None


def _as_datetime(value: Any) -> datetime | None:
    """``value`` (a datetime or an ISO string, tz dropped) as a naive datetime."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=None)


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


# Resource types whose own clinical time places them in the ED window.
_TIME_ROUTED_TYPES: frozenset[str] = frozenset(
    {
        "Observation",
        "ServiceRequest",
        "DiagnosticReport",
        "MedicationRequest",
        "MedicationAdministration",
        "Procedure",
        "ImagingStudy",
    }
)
# The imaging report Composition (LOINC 18748-4) is routed by the start of the
# ImagingStudy it describes, not by its own (report-issue) date.
_IMAGING_REPORT_LOINC = "18748-4"
_IMAGING_STUDY_REF_PREFIX = "ImagingStudy/"
# Clinical-time fields in precedence order: (top-level field, Period field).
_CLINICAL_TIME_FIELDS: tuple[tuple[str, str | None], ...] = (
    ("effectiveDateTime", None),
    ("effectivePeriod", "start"),
    ("effectiveInstant", None),
    ("performedDateTime", None),
    ("performedPeriod", "start"),
    ("authoredOn", None),
    ("occurrenceDateTime", None),
    ("started", None),
)
_TZ_TAIL_RE = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")


def _naive_local(value: Any) -> datetime | None:
    """Parse an ISO datetime string to a naive local datetime (the zone
    suffix is dropped: the CIF times are local and so is the window)."""
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        return datetime.fromisoformat(_TZ_TAIL_RE.sub("", value))
    except ValueError:
        return None


def _ed_window(ctx: Any) -> tuple[datetime, datetime] | None:
    """``[admission - admitted_ed_stay(), admission)`` of a via-ED admission
    (the bridge Encounter's period), cached on ctx; None when not via ED."""
    cached = getattr(ctx, "_ed_window_cache", None)
    if cached is not None:
        return cached if cached is not False else None
    window: tuple[datetime, datetime] | None = None
    if _resolve_ed_imp_id(ctx) is not None:
        adm = _naive_local(str(get_attr_or_key(ctx.record["encounters"][0], "admission_datetime", "") or ""))
        if adm is not None:
            window = (adm - admitted_ed_stay(), adm)
    try:
        ctx._ed_window_cache = window if window is not None else False  # noqa: SLF001
    except AttributeError:
        pass
    return window


def ed_window_of_record(record: Any) -> tuple[datetime, datetime] | None:
    """The ED window of a record's via-ED admission (None when not via ED), for
    callers that hold the record and not the bundle context (Issue #3958)."""
    return _ed_window(SimpleNamespace(record=record))


def time_in_ed_window(window: tuple[datetime, datetime] | None, value: Any) -> bool:
    """Whether ``value`` (a datetime or an ISO string) lies in the ED window
    ``[start, end)``; the one predicate that routes a resource to the bridge."""
    at = _as_datetime(value)
    return window is not None and at is not None and window[0] <= at < window[1]


def _clinical_time(resource: dict) -> datetime | None:
    for field, sub in _CLINICAL_TIME_FIELDS:
        v = resource.get(field)
        if sub is not None:
            v = v.get(sub) if isinstance(v, dict) else None
        parsed = _naive_local(v)
        if parsed is not None:
            return parsed
    return None


def _encounter_field(resource: dict) -> str:
    """The element carrying a resource's Encounter reference: R4
    ``MedicationAdministration`` uses ``context``, the others ``encounter``."""
    return "context" if resource.get("resourceType") == "MedicationAdministration" else "encounter"


def _imaging_study_starts(ctx: Any) -> dict[str, datetime]:
    """FHIR ImagingStudy id -> start of the record's imaging studies, cached on ctx."""
    cached = getattr(ctx, "_imaging_study_starts_cache", None)
    if cached is not None:
        return cached
    from clinosim.modules.output.fhir_r4.labs.imaging_study import imaging_study_id_for_cif_study_id

    starts: dict[str, datetime] = {}
    ext = ctx.record.get("extensions") if isinstance(ctx.record, dict) else None
    for study in (ext or {}).get("imaging") or []:
        sid = str(get_attr_or_key(study, "study_id", "") or "")
        started = get_attr_or_key(study, "started_datetime", None)
        at = _as_datetime(started)
        if sid and at is not None:
            starts[imaging_study_id_for_cif_study_id(sid)] = at
    try:
        ctx._imaging_study_starts_cache = starts  # noqa: SLF001
    except AttributeError:
        pass
    return starts


def _imaging_report_time(resource: dict, ctx: Any) -> datetime | None:
    """Start of the ImagingStudy an imaging-report Composition describes
    (None for any other resource or an unlinked report)."""
    if resource.get("resourceType") != "Composition":
        return None
    if not any(c.get("code") == _IMAGING_REPORT_LOINC for c in (resource.get("type") or {}).get("coding") or []):
        return None
    starts = _imaging_study_starts(ctx)
    for section in resource.get("section") or []:
        for ref in section.get("entry") or []:
            r = str(ref.get("reference", "")) if isinstance(ref, dict) else ""
            if r.startswith(_IMAGING_STUDY_REF_PREFIX) and r[len(_IMAGING_STUDY_REF_PREFIX) :] in starts:
                return starts[r[len(_IMAGING_STUDY_REF_PREFIX) :]]
    return None


def reattribute_ed_phase_by_time(resource: dict, ctx: Any) -> None:
    """Route an order, result, dose or procedure dated in the ED window of a
    via-ED admission from the IMP Encounter to the ``-ED`` bridge
    (Issue #3672). Idempotent; resources without a parsable clinical time,
    documents, and anything already routed elsewhere stay untouched."""
    imaging_report_at = _imaging_report_time(resource, ctx)
    if resource.get("resourceType") not in _TIME_ROUTED_TYPES and imaging_report_at is None:
        return
    imp_id = _resolve_ed_imp_id(ctx)
    if imp_id is None:
        return
    enc_ref = resource.get(_encounter_field(resource))
    imp_ref = f"Encounter/{resolve_encounter_id(imp_id)}"
    if not isinstance(enc_ref, dict) or enc_ref.get("reference") != imp_ref:
        return
    window = _ed_window(ctx)
    if window is None:
        return
    t = imaging_report_at if imaging_report_at is not None else _clinical_time(resource)
    if not time_in_ed_window(window, t):
        return
    enc_ref["reference"] = f"Encounter/{resolve_encounter_id(f'{imp_id}-ED')}"
    _name_ed_physician_as_requester(resource, ctx)


# Orders carry the ordering physician in ``requester``. MedicationRequest.recorder
# (medications.py) and the ServiceRequest.performer fallback (service_request.py)
# repeat that same Practitioner when no other one is known.
_REQUESTER_MIRROR_FIELDS: dict[str, str] = {"MedicationRequest": "recorder", "ServiceRequest": "performer"}


def _ed_physician_id(ctx: Any) -> str:
    """``ed_physician_id`` of the via-ED IMP encounter ('' when unset)."""
    return str(get_attr_or_key(ctx.record["encounters"][0], "ed_physician_id", "") or "")


def _name_ed_physician_as_requester(resource: dict, ctx: Any) -> None:
    """An order re-routed to the ED bridge is requested by the stay's ED physician
    (the bridge Encounter's attender, Issue #3888), not by the inpatient
    attending whose name the order carries. The reference form is the one the
    order builders emit. No ED physician recorded: left unchanged."""
    rtype = resource.get("resourceType")
    if rtype not in _REQUESTER_MIRROR_FIELDS:
        return
    ed_doc = _ed_physician_id(ctx)
    requester = resource.get("requester")
    if not ed_doc or not isinstance(requester, dict):
        return
    new_ref = {"reference": f"Practitioner/{ed_doc}"}
    mirror = _REQUESTER_MIRROR_FIELDS[rtype]
    value = resource.get(mirror)
    if rtype == "MedicationRequest" and value == requester:
        resource[mirror] = dict(new_ref)
    elif rtype == "ServiceRequest" and value == [requester]:
        resource[mirror] = [dict(new_ref)]
    resource["requester"] = new_ref
