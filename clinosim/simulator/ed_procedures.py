"""Timing of the bedside procedures performed in an ED visit (Issue #2863).

The procedure engine places a bedside procedure hours into an admission; an
ED visit lasts a few hours, so its procedures are placed on the visit's own
workflow instead: arrival procedures with the triage vitals (IV access no
later than the first IV drug order), fracture care after the imaging read,
everything else after the treatment orders, one after another. Every
procedure then fits inside the visit. Only start / end move: the engine's
draws are kept, so no random stream shifts.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from clinosim.simulator._ed_thresholds import (
    ED_ARRIVAL_PROCEDURES,
    ED_IMAGING_READ_MIN,
    ED_POST_IMAGING_PROCEDURES,
    ED_TREATMENT_ORDER_OFFSET_MEAN_MIN,
    ED_VITALS_OFFSET_MIN,
)
from clinosim.simulator.encounter_setup import fit_procedures_in_stay
from clinosim.types.encounter import Encounter, Order, OrderType
from clinosim.types.procedure import ProcedureRecord

__all__ = ["time_ed_procedures"]


def _is_iv(order: Order) -> bool:
    return order.order_type == OrderType.MEDICATION and str(order.route or "").upper().startswith("IV")


def time_ed_procedures(procedures: list[ProcedureRecord], orders: list[Order], encounter: Encounter) -> None:
    """Place ``procedures`` on the ED visit's workflow, inside its period."""
    arrival = encounter.admission_datetime
    rooming = arrival + timedelta(minutes=ED_VITALS_OFFSET_MIN)
    iv_orders = [o.ordered_datetime for o in orders if _is_iv(o)]
    imaging = [o.ordered_datetime for o in orders if o.order_type == OrderType.IMAGING]
    after_treatment = arrival + timedelta(minutes=ED_TREATMENT_ORDER_OFFSET_MEAN_MIN)
    after_imaging = max(imaging) + timedelta(minutes=ED_IMAGING_READ_MIN) if imaging else after_treatment

    previous_end: datetime | None = None
    for p in procedures:
        length = p.end_datetime - p.start_datetime
        if p.procedure_type in ED_ARRIVAL_PROCEDURES:
            start = rooming
            if p.procedure_type == "iv_line" and iv_orders:
                start = max(arrival, min(start, min(iv_orders)))
        else:
            start = after_imaging if p.procedure_type in ED_POST_IMAGING_PROCEDURES else after_treatment
            if previous_end is not None:
                start = max(start, previous_end)
            previous_end = start + length
        p.start_datetime, p.end_datetime = start, start + length
    fit_procedures_in_stay(procedures, arrival, encounter.discharge_datetime)
