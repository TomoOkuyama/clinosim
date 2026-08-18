"""FHIR R4 oxygen-therapy session builder — Procedure with performedPeriod.

## Clinical / hospital reality

Oxygen therapy is administered as a "session": placed at admission (or when
hypoxia is detected), titrated to a target SpO2, and stopped when the
patient no longer needs supplemental oxygen. Representing that session as a
single point-in-time Procedure (`performedDateTime`) loses the clinically
important duration — a consumer sees the placement instant but cannot
answer "when did we stop O2?".

## Emission model — encounter-centric, Order optional

Coverage rule (from consumer feedback session 88j):
**every encounter with `on_supplemental_oxygen=True` vitals emits one
Procedure**, regardless of whether an explicit O2 Order was placed in the
disease-YAML `supportive_care` section.

Historical shape of the CIF: only the 9 respiratory / cardiac diseases whose
YAML included `{type: "O2", …}` produced an O2 Order. The vitals pipeline
(`simulator/vitals_pipeline.py::_o2_for`) independently places any inpatient
on supplemental O2 when SpO2 drops below the hypoxemia threshold — so
patients with pyelonephritis, stroke, DKA, hip fracture, influenza, etc.
receive supplemental O2 in the vitals record without an accompanying Order.
Restricting Procedure emission to encounters with an O2 Order missed ~34%
of these episodes.

Per encounter with on-O2 vitals, one **Procedure** resource is emitted:

- `code.coding` = SNOMED CT 57485005 "Oxygen therapy (procedure)".
- `code.text` = clean localised label ("酸素投与" / "Oxygen therapy") —
  the SpO2 target no longer contaminates this field (moved to `note[]`).
- `performedPeriod` = derived session start/end (see below).
- `note[]` = SpO2 target — only when an Order exists and its display
  carried one. Vitals-only emissions omit `note[]`.
- `usedCode[]` = SNOMED coding of the delivery device (nasal cannula /
  simple mask / …) derived from the vitals `oxygen_delivery_device` mode.
  `usedCode` is `CodeableConcept` and does not require a matching Device
  resource, so it is spec-safe without a companion Device emission.
- **no `bodySite`** — oxygen therapy has no anatomical site concept, and
  the generic "処置部位不明" placeholder used by `_bb_procedures` is
  misleading here.

Session boundaries come from `ctx.record.vital_signs`:

- start: `min(order.ordered_datetime, first on-O2 vital)` when an Order
  exists (on-O2 measurement can precede formal order entry — pick the
  earlier); otherwise just `first on-O2 vital`.
- end: last vital where `on_supplemental_oxygen=True`; if the last recorded
  vital of the encounter is still on O2, the encounter discharge datetime
  is used as the end proxy (patient still on O2 at discharge / snapshot).

If no on-O2 vitals exist for the encounter (the order was placed but the
patient never went on supplemental O2 per vitals), the Procedure is
skipped — no fabrication.

Performer attribution: `Order.ordered_by` when an Order exists (physician
who placed the order); otherwise the encounter's `attending_physician_id`
(the physician responsible for the episode of care); otherwise omitted.

DeviceUseStatement is deferred as future work: DUS.device is `1..1
Reference(Device)`, which requires either a per-patient Device resource
or a shared facility-level Device (matching the infusion-pump pattern in
`encounters/facility.py`). The Procedure alone with `performedPeriod` +
`usedCode` already answers the "when + which device" question consumers
need — DUS is added value, not the primary fix.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output.fhir_r4.conditions.primary_ref import primary_condition_ref
from clinosim.modules.output.fhir_r4.lib.common import BundleContext, to_fhir_datetime

logger = logging.getLogger(__name__)

# session-88j P1-8: dwell time applied when an encounter has only a single
# on-O2 vital timestamp (start == end after `_oxygen_session_period`).
# Previously the caller silently `continue`d such encounters, losing every
# short-observation O2 session — for real p=200 seed=300 JP cohorts these
# accounted for a small but non-zero slice of on-O2 encounters. We fill
# `end = start + 15 min` (mid-value of a typical hourly vitals sweep
# window) and annotate the Procedure `note[]` so the estimate is explicit
# and never confused with a recorded stop time.
_SINGLE_TIMESTAMP_DWELL = timedelta(minutes=15)

# SNOMED CT concept for oxygen therapy — well-established procedure code
# recognised by JP Core / US Core consumers. Registered in
# codes/data/snomed-ct.yaml so `code_lookup` resolves the JA/EN display.
_SNOMED_OXYGEN_THERAPY = "57485005"

# SNOMED CT concepts for delivery devices — registered in
# codes/data/snomed-ct.yaml. Used only for `Procedure.usedCode[]`.
_SNOMED_DEVICE_BY_MODE: dict[str, str] = {
    "nasal_cannula": "336623009",  # Nasal cannula (physical object)
    "simple_mask": "425574000",  # Simple face mask (physical object)
    "venturi": "336623009",  # No dedicated SNOMED — fallback to nasal cannula concept
    "non-rebreather": "425574000",  # Non-rebreather variant of face mask concept
    "HFNC": "336623009",  # No dedicated HFNC SNOMED — fallback
    "BiPAP": "26412008",  # Ventilator concept (BiPAP is NPPV)
    "ventilator": "26412008",  # Mechanical ventilator (physical object)
}


def is_oxygen_order(order: Any) -> bool:
    """Return True for an oxygen-therapy Order.

    Match by display_name prefix ("O2:") which is the canonical shape emitted
    by the supportive-order path in `modules/order/engine.py`. Public helper
    so `_bb_procedures` can skip these Orders (they are handled here).
    """
    display = str(_o(order, "display_name", "") or "")
    return display.startswith("O2:") or display.startswith("O2 ")


def _oxygen_target_note(display_name: str) -> str:
    """Extract the SpO2 target phrase from an O2 order display_name.

    Returns "" when the display carries no target (nothing to note).
    Example: "O2: Nasal cannula SpO2 >= 94%" → "SpO2 >= 94%"
    """
    body = display_name.split(":", 1)[-1].strip()
    for marker in ("SpO2", "SpO₂", "目標"):
        if marker in body:
            return body[body.index(marker) :].strip()
    return ""


def _pick_device_mode(vitals_on_o2: list[Any]) -> str:
    """Return the most common oxygen_delivery_device across on-O2 vitals."""
    devs = [str(_o(v, "oxygen_delivery_device", "") or "") for v in vitals_on_o2]
    devs = [d for d in devs if d]
    if not devs:
        return ""
    return Counter(devs).most_common(1)[0][0]


def _fill_single_timestamp_end(ts: str) -> str:
    """Add ``_SINGLE_TIMESTAMP_DWELL`` to ``ts`` and return the ISO string.

    Returns the input verbatim if the timestamp cannot be parsed — the caller
    treats that as an unfillable session and drops it (logged with reason
    ``same_ts_unparseable``). Accepts either naive or timezone-aware ISO 8601
    inputs; the offset (or lack of one) is preserved so downstream
    ``to_fhir_datetime`` treats the filled end identically to the original
    start.
    """
    if not ts:
        return ts
    try:
        # datetime.fromisoformat handles both naive ("2025-06-21T18:11:00")
        # and offset-aware ("2025-06-21T18:11:00+09:00") variants used by CIF.
        parsed = datetime.fromisoformat(ts)
    except ValueError:
        return ts
    filled = parsed + _SINGLE_TIMESTAMP_DWELL
    # Preserve the original suffix shape — isoformat drops microseconds
    # when they are zero (matching the input format). This keeps
    # to_fhir_datetime idempotent regardless of tz-awareness.
    return filled.isoformat()


def _oxygen_session_period(
    order: Any | None,
    encounter_id: str,
    encounter_end: str,
    vitals: list[Any],
) -> tuple[str, str, str] | None:
    """Return (start_iso, end_iso, device_mode) for the O2 session, or None
    when the encounter has no on-supplemental-oxygen vitals.

    `order` is optional — when None, the session start is the first on-O2
    vital timestamp; when present, the earlier of `order.ordered_datetime`
    and the first on-O2 vital is used.

    Single session per encounter — the simulator does not currently model
    discontinue+restart. If future disease YAMLs express interrupted O2
    courses, this helper is the seam that would split them.
    """
    ordered_dt = str(_o(order, "ordered_datetime", "") or "") if order is not None else ""
    vitals_here = [v for v in vitals if str(_o(v, "encounter_id", "") or "") == encounter_id]
    if not vitals_here:
        # Vitals sometimes don't carry encounter_id — fall back to all vitals
        # (typical for a single-encounter record).
        vitals_here = list(vitals)
    on_o2 = [v for v in vitals_here if bool(_o(v, "on_supplemental_oxygen", False))]
    if not on_o2:
        return None

    def _ts(v: Any) -> str:
        return str(_o(v, "timestamp", "") or "")

    ts_sorted = sorted(_ts(v) for v in on_o2 if _ts(v))
    first_on = ts_sorted[0] if ts_sorted else ""
    last_on = ts_sorted[-1] if ts_sorted else ""

    if ordered_dt and first_on:
        start = min(ordered_dt, first_on)
    else:
        start = ordered_dt or first_on

    all_ts = sorted(_ts(v) for v in vitals_here if _ts(v))
    last_recorded = all_ts[-1] if all_ts else ""
    if last_on and last_recorded and last_on == last_recorded and encounter_end:
        end = str(encounter_end)
    else:
        end = last_on

    device = _pick_device_mode(on_o2)
    return start, end, device


def _encounter_end_index(ctx: BundleContext) -> dict[str, str]:
    """Return a map `encounter_id -> discharge_datetime` for session-end lookup."""
    idx: dict[str, str] = {}
    for e in ctx.record.get("encounters", []) or []:
        eid = _o(e, "encounter_id", "") or ""
        end = _o(e, "discharge_datetime", "") or ""
        if eid:
            idx[eid] = str(end) if end else ""
    return idx


def _encounter_attending_index(ctx: BundleContext) -> dict[str, str]:
    """Return a map `encounter_id -> attending_physician_id` for performer
    fallback when no O2 Order is present."""
    idx: dict[str, str] = {}
    for e in ctx.record.get("encounters", []) or []:
        eid = _o(e, "encounter_id", "") or ""
        att = _o(e, "attending_physician_id", "") or ""
        if eid and att:
            idx[eid] = str(att)
    return idx


def _bb_oxygen_therapy(ctx: BundleContext) -> list[dict]:
    """Emit Procedure resources for oxygen-therapy sessions.

    Encounter-centric: emits one Procedure per encounter that has any
    `on_supplemental_oxygen=True` vitals. When an O2 Order (display_name
    starts with "O2:") is present for that encounter, it enriches the
    Procedure with ordered_datetime (for session start), ordered_by (for
    performer), and the SpO2 target note. Otherwise the Procedure is
    derived purely from vitals + encounter attending.
    """
    vitals = ctx.record.get("vital_signs", []) or []

    # Early-out: no on-O2 vitals anywhere → nothing to emit. Cheap short-
    # circuit before we walk encounters and index orders.
    if not any(bool(_o(v, "on_supplemental_oxygen", False)) for v in vitals):
        return []

    # Iterate over encounters (not vitals). CIF vital_signs records do NOT
    # carry `encounter_id` — they are implicitly scoped to the enclosing
    # per-encounter CIF file. `_oxygen_session_period` already handles that
    # by falling back to all vitals when the encounter-id filter yields
    # nothing.
    encounters = ctx.record.get("encounters", []) or []
    if not encounters:
        return []

    # Index O2 Orders by encounter_id — one per encounter in practice; if
    # multiple exist, the earliest ordered_datetime wins so the Procedure
    # start reflects the first orderable event.
    orders = ctx.record.get("orders", []) or []
    o2_orders_by_enc: dict[str, list[Any]] = defaultdict(list)
    for o in orders:
        if is_oxygen_order(o):
            eid = str(_o(o, "encounter_id", "") or "")
            if eid:
                o2_orders_by_enc[eid].append(o)

    enc_end_idx = _encounter_end_index(ctx)
    enc_att_idx = _encounter_attending_index(ctx)
    lang = resolve_lang(ctx.country)
    is_jp_out = is_jp(ctx.country)
    proc_display = code_lookup("snomed-ct", _SNOMED_OXYGEN_THERAPY, lang) or "Oxygen therapy"

    out: list[dict] = []
    # Iterate encounters in the record's own order so resource output is
    # stable and matches the order they were admitted / discharged in.
    for encounter in encounters:
        enc_id = str(_o(encounter, "encounter_id", "") or "")
        if not enc_id:
            continue
        orders_here = o2_orders_by_enc.get(enc_id, [])
        # Pick the earliest-ordered O2 Order (if any) so session start
        # reflects the first documented orderable event.
        order = min(
            orders_here,
            key=lambda o: str(_o(o, "ordered_datetime", "") or ""),
            default=None,
        )

        session = _oxygen_session_period(order, enc_id, enc_end_idx.get(enc_id, ""), vitals)
        if not session:
            # Observable drop reason: no on-O2 vitals for this encounter.
            logger.info(
                "oxygen_therapy: skipped encounter=%s reason=no_on_o2_vitals patient=%s",
                enc_id,
                ctx.patient_id,
            )
            continue
        start, end, device_mode = session
        session_filled_from_single_ts = False
        if not start:
            logger.info(
                "oxygen_therapy: skipped encounter=%s reason=start_missing patient=%s",
                enc_id,
                ctx.patient_id,
            )
            continue
        if not end:
            logger.info(
                "oxygen_therapy: skipped encounter=%s reason=end_missing patient=%s",
                enc_id,
                ctx.patient_id,
            )
            continue
        if start == end:
            # session-88j P1-8: previously skipped. Now fill a short dwell
            # window so short-observation O2 episodes still produce a
            # Procedure with `performedPeriod` and are annotated so the
            # estimate is auditable.
            filled_end = _fill_single_timestamp_end(end)
            if filled_end and filled_end != end:
                end = filled_end
                session_filled_from_single_ts = True
                logger.info(
                    "oxygen_therapy: same_ts_filled encounter=%s patient=%s dwell_minutes=%d",
                    enc_id,
                    ctx.patient_id,
                    int(_SINGLE_TIMESTAMP_DWELL.total_seconds() // 60),
                )
            else:
                logger.info(
                    "oxygen_therapy: skipped encounter=%s reason=same_ts_unparseable patient=%s ts=%s",
                    enc_id,
                    ctx.patient_id,
                    start,
                )
                continue

        order_id = str(_o(order, "order_id", "") or "") if order is not None else ""
        ordered_by = str(_o(order, "ordered_by", "") or "") if order is not None else ""
        display_name = str(_o(order, "display_name", "") or "") if order is not None else ""
        target_note = _oxygen_target_note(display_name) if display_name else ""

        if order_id:
            proc_id = f"proc-o2-{order_id}"
        elif enc_id:
            proc_id = f"proc-o2-{enc_id}"
        else:
            proc_id = f"proc-o2-{ctx.patient_id}-{len(out) + 1:04d}"

        procedure: dict[str, Any] = {
            "resourceType": "Procedure",
            "id": proc_id,
            **(
                {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure"]}}
                if is_jp_out
                else {}
            ),
            "status": "completed",
            "category": {
                "coding": [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": "277132007",  # SNOMED Therapeutic procedure — matches _bb_procedures default
                        "display": code_lookup("snomed-ct", "277132007", lang) or "Therapeutic procedure",
                    }
                ],
            },
            "code": {
                "coding": [
                    {
                        "system": get_system_uri("snomed-ct"),
                        "code": _SNOMED_OXYGEN_THERAPY,
                        "display": proc_display,
                    }
                ],
                "text": "酸素投与" if is_jp_out else "Oxygen therapy",
            },
            "subject": {"reference": f"Patient/{ctx.patient_id}"},
            "performedPeriod": {
                "start": to_fhir_datetime(start),
                "end": to_fhir_datetime(end),
            },
        }
        if enc_id:
            procedure["encounter"] = {"reference": f"Encounter/{enc_id}"}
            # Chronic-primary encounters resolve to the patient-scoped chronic
            # Condition; acute-primary encounters keep the encounter-scoped id.
            _primary_ref = primary_condition_ref(ctx.record, ctx.patient_id, enc_id)
            procedure["reasonReference"] = [{"reference": f"Condition/{_primary_ref}"}]

        performer_ref = ordered_by or enc_att_idx.get(enc_id, "")
        if performer_ref:
            procedure["performer"] = [{"actor": {"reference": f"Practitioner/{performer_ref}"}}]
        notes: list[dict[str, str]] = []
        if target_note:
            notes.append({"text": f"投与目標: {target_note}" if is_jp_out else f"Target: {target_note}"})
        if session_filled_from_single_ts:
            # session-88j P1-8: mark filled sessions so consumers can tell
            # a recorded stop time from an estimated one.
            _fill_note = (
                "単一測定時点のみに基づく推定 (dwell 15 分)"
                if is_jp_out
                else "Estimated from a single on-O2 measurement (15 min dwell)"
            )
            notes.append({"text": _fill_note})
        if notes:
            procedure["note"] = notes
        # Procedure.usedCode carries the delivery device concept without
        # requiring a Device resource — CodeableConcept, min=0, max=* in
        # Procedure R4. Emit only when the vitals actually name a device.
        device_snomed = _SNOMED_DEVICE_BY_MODE.get(device_mode) if device_mode else ""
        if device_snomed:
            device_display = code_lookup("snomed-ct", device_snomed, lang) or device_mode
            procedure["usedCode"] = [
                {
                    "coding": [
                        {
                            "system": get_system_uri("snomed-ct"),
                            "code": device_snomed,
                            "display": device_display,
                        }
                    ],
                    "text": device_display,
                }
            ]
        out.append(procedure)

    return out
