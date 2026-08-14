"""FHIR R4 oxygen-therapy session builder — Procedure with performedPeriod.

## Clinical / hospital reality

Oxygen therapy is administered as a "session": placed at admission (or when
hypoxia is detected), titrated to a target SpO2, and stopped when the
patient no longer needs supplemental oxygen. Representing that session as a
single point-in-time Procedure (`performedDateTime`) loses the clinically
important duration — a consumer sees the placement instant but cannot
answer "when did we stop O2?".

## FHIR shape emitted

Per encounter with an oxygen-therapy Order **and** matching on-O2 vitals,
one **Procedure** resource is emitted:

- `code.coding` = SNOMED CT 57485005 "Oxygen therapy (procedure)".
- `code.text` = clean localised label ("酸素投与" / "Oxygen therapy") —
  the SpO2 target no longer contaminates this field (moved to `note[]`).
- `performedPeriod` = derived session start/end (see below).
- `note[]` = SpO2 target (if the Order display carried one).
- `usedCode[]` = SNOMED coding of the delivery device (nasal cannula /
  simple mask / …) derived from the vitals `oxygen_delivery_device` mode.
  `usedCode` is `CodeableConcept` and does not require a matching Device
  resource, so it is spec-safe without a companion Device emission.
- **no `bodySite`** — oxygen therapy has no anatomical site concept, and
  the generic "処置部位不明" placeholder used by `_bb_procedures` is
  misleading here.

Session boundaries come from `ctx.record.vital_signs`:

- start: `min(order.ordered_datetime, first on-O2 vital)` (on-O2 measurement
  can precede formal order entry — pick the earlier).
- end: last vital where `on_supplemental_oxygen=True`; if the last recorded
  vital of the encounter is still on O2, the encounter discharge datetime
  is used as the end proxy (patient still on O2 at discharge / snapshot).

If no on-O2 vitals exist for the encounter (the order was placed but the
patient never went on supplemental O2 per vitals), the Procedure is
skipped — no fabrication.

DeviceUseStatement is deferred as future work: DUS.device is `1..1
Reference(Device)`, which requires either a per-patient Device resource
or a shared facility-level Device (matching the infusion-pump pattern in
`encounters/facility.py`). The Procedure alone with `performedPeriod` +
`usedCode` already answers the "when + which device" question consumers
need — DUS is added value, not the primary fix.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output.fhir_r4.lib.common import BundleContext, to_fhir_datetime

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


def _oxygen_session_period(
    order: Any,
    encounter_id: str,
    encounter_end: str,
    vitals: list[Any],
) -> tuple[str, str, str] | None:
    """Return (start_iso, end_iso, device_mode) for the O2 session, or None
    when the encounter has no on-supplemental-oxygen vitals.

    Single session per Order — the simulator does not currently model
    discontinue+restart. If future disease YAMLs express interrupted O2
    courses, this helper is the seam that would split them.
    """
    ordered_dt = str(_o(order, "ordered_datetime", "") or "")
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

    start = min(ordered_dt, first_on) if ordered_dt and first_on else (ordered_dt or first_on)

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


def _bb_oxygen_therapy(ctx: BundleContext) -> list[dict]:
    """Emit Procedure resources for oxygen-therapy sessions."""
    orders = ctx.record.get("orders", []) or []
    o2_orders = [o for o in orders if is_oxygen_order(o)]
    if not o2_orders:
        return []

    vitals = ctx.record.get("vital_signs", []) or []
    enc_end_idx = _encounter_end_index(ctx)
    lang = resolve_lang(ctx.country)
    is_jp_out = is_jp(ctx.country)
    proc_display = code_lookup("snomed-ct", _SNOMED_OXYGEN_THERAPY, lang) or "Oxygen therapy"

    out: list[dict] = []
    for order in o2_orders:
        enc_id = str(_o(order, "encounter_id", "") or "")
        session = _oxygen_session_period(order, enc_id, enc_end_idx.get(enc_id, ""), vitals)
        if not session:
            continue
        start, end, device_mode = session
        if not start or not end or start == end:
            continue

        order_id = str(_o(order, "order_id", "") or "")
        ordered_by = str(_o(order, "ordered_by", "") or "")
        display_name = str(_o(order, "display_name", "") or "")
        target_note = _oxygen_target_note(display_name)

        proc_id = f"proc-o2-{order_id}" if order_id else f"proc-o2-{ctx.patient_id}-{len(out) + 1:04d}"

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
            procedure["reasonReference"] = [{"reference": f"Condition/cond-{enc_id}-primary"}]
        if ordered_by:
            procedure["performer"] = [{"actor": {"reference": f"Practitioner/{ordered_by}"}}]
        notes: list[dict[str, str]] = []
        if target_note:
            notes.append({"text": f"投与目標: {target_note}" if is_jp_out else f"Target: {target_note}"})
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
