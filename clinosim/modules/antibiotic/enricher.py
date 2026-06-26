"""Antibiotic enricher (PR3b-1, POST_ENCOUNTER stage, order=85).

Always-on (AD-55 near-essential clinical cascade Module). Consumes
extensions["hai"] from PR-B. For each HAIEvent whose onset is on/before
the snapshot date (AD-32 future-onset skip), materializes the IDSA
empirical regimen as:
  - 1 Order(MEDICATION) per drug, appended to record.orders, so the
    existing _fhir_medications.py builder emits MedicationRequest.
  - N MedicationAdministration per regimen, appended to
    record.medication_administrations, so the same builder emits MAR.
  - 1 AntibioticRegimen per drug, appended to
    record.extensions["antibiotic"], for PR3b-2/3/4 consumption.

AD-32 future-onset skip rationale: inpatient.py:464-490 runs AD-32
HAI/microbiology truncation AFTER POST_ENCOUNTER stage completes. If
this enricher emits Order+MAR for a future-onset HAI event, the
truncation drops the HAI event but leaves the orphan Order — a CIF
data quality defect. The enricher pre-skips future-onset events.
"""
from __future__ import annotations

from datetime import datetime

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS
from clinosim.modules.antibiotic.engine import build_regimens, generate_mar_doses
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.hai import HAIEvent


_ORDER_HOUR = 8  # empirical = "AM round" same day as onset


_DEFAULT_SNAPSHOT_FALLBACK = "2099-12-31"


def _resolve_snapshot(cfg) -> datetime:
    """Return the simulation snapshot datetime (AD-32).

    PR-93 adversarial review fix: guard against empty / malformed
    ``time_range``. Previously ``time_range=()`` would raise IndexError
    on ``[-1]``; now falls back to the hardcoded 2099-12-31 sentinel
    (matching the no-time_range default behaviour).
    """
    snap = _get(cfg, "snapshot_date", None)
    if snap:
        return datetime.fromisoformat(snap)
    time_range = _get(cfg, "time_range", None) or ()
    if isinstance(time_range, (list, tuple)) and time_range:
        end = time_range[-1]
    else:
        end = _DEFAULT_SNAPSHOT_FALLBACK
    try:
        return datetime.fromisoformat(end)
    except (TypeError, ValueError):
        return datetime.fromisoformat(_DEFAULT_SNAPSHOT_FALLBACK)


def enrich_antibiotic(ctx) -> None:
    """POST_ENCOUNTER stage entry point — see module docstring."""
    snapshot = _resolve_snapshot(ctx.config)
    snapshot_date = snapshot.date()
    for rec in ctx.records:
        ext = _get(rec, "extensions", {}) or {}
        hai_events: list[HAIEvent] = list(ext.get("hai", []) or [])
        if not hai_events:
            continue
        regimens_out = []
        for ev in hai_events:
            try:
                onset_date = datetime.fromisoformat(ev.onset_date).date()
            except (TypeError, ValueError):
                continue
            if onset_date > snapshot_date:
                # AD-32 defensive skip: future-onset HAI gets truncated
                # by inpatient.py:464-490 AFTER POST_ENCOUNTER. Pre-skip
                # here to prevent orphan Order/MAR.
                continue
            start_dt = datetime.fromisoformat(ev.onset_date).replace(hour=_ORDER_HOUR)
            for regimen in build_regimens(ev, start_datetime=start_dt):
                order_id = f"req-{regimen.regimen_id}"
                order = Order(
                    order_id=order_id,
                    encounter_id=regimen.encounter_id,
                    patient_id=_get(_get(rec, "patient", None), "patient_id", ""),
                    order_type=OrderType.MEDICATION,
                    display_name=ANTIBIOTIC_DRUGS.get(regimen.drug_key, {}).get(
                        "name", regimen.drug_key
                    ),
                    ordered_datetime=regimen.start_datetime,
                    status=OrderStatus.ACCEPTED,
                    dose_unit=regimen.dose,
                    frequency=regimen.frequency,
                    route=regimen.route,
                    duration_days=regimen.duration_days,
                    reason_condition=regimen.hai_event_id,
                )
                if isinstance(rec, dict):
                    rec.setdefault("orders", []).append(order)
                else:
                    rec.orders.append(order)
                mars = generate_mar_doses(regimen, snapshot_datetime=snapshot,
                                          order_id=order_id)
                if isinstance(rec, dict):
                    rec.setdefault("medication_administrations", []).extend(mars)
                else:
                    rec.medication_administrations.extend(mars)
                regimens_out.append(regimen)
        if regimens_out:
            if isinstance(rec, dict):
                rec.setdefault("extensions", {}).setdefault("antibiotic", []).extend(regimens_out)
            else:
                rec.extensions.setdefault("antibiotic", []).extend(regimens_out)
