"""Weaning vasopressor / inotrope infusions and the discharge gate after them
(Issue #3270).

A vasopressor or inotrope (``trigger_classes`` of
``reference_data/vasoactive_hold.yaml``) given as a continuous infusion runs
until the patient no longer needs it: at the start of a hospital day the
running infusions stop together once the recorded pressures of the preceding
window met the mean-arterial-pressure target and the patient is out of shock
(``stop_weaned_vasoactive_infusions``). The discharge gate keeps the
patient in hospital while an infusion ran within the observation period
before discharge (``vasoactive_support_after``). Values live in
``reference_data/vasoactive_weaning.yaml``. Everything here is RNG-free.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clinosim.codes.drugs import drug_ref
from clinosim.datafiles import load_data_yaml
from clinosim.simulator._discharge_gate_thresholds import MAP_PULSE_PRESSURE_FRACTION
from clinosim.simulator.medication_pipeline import is_vasoactive_infusion
from clinosim.types.encounter import MedicationAdministration, Order, OrderStatus, VitalSignRecord


class VasoactiveWeaningRules(BaseModel):
    """Schema of ``reference_data/vasoactive_weaning.yaml`` (Issue #3270)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    map_target_mmhg: float = Field(gt=0)
    stable_hours: int = Field(gt=0)
    min_bp_readings: int = Field(ge=1)
    off_support_days_before_discharge: int = Field(ge=1)
    max_extension_days: int = Field(ge=0)


@functools.cache
def vasoactive_weaning_rules() -> VasoactiveWeaningRules:
    """The validated weaning and post-support discharge rules."""
    return VasoactiveWeaningRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "vasoactive_weaning.yaml")
    )


def mean_arterial_pressure(systolic: float, diastolic: float) -> float:
    """Mean arterial pressure from a cuff reading: diastolic plus a third of
    the pulse pressure."""
    return diastolic + (systolic - diastolic) * MAP_PULSE_PRESSURE_FRACTION


def hospital_day_start(admission_time: datetime, day: int) -> datetime:
    """Midnight starting calendar day ``day`` of the stay (day 0 = the
    admission date) — the calendar day the MAR of loop day ``day`` covers."""
    return datetime.combine(admission_time.date() + timedelta(days=day), datetime.min.time())


def _started_at(order: Order, mars: Iterable[MedicationAdministration]) -> datetime:
    """When the infusion began: its order time, or its first given dose when
    that was charted earlier."""
    start = max(order.ordered_datetime, order.administer_from) if order.administer_from else order.ordered_datetime
    for mar in mars:
        if mar.order_id == order.order_id and mar.status == "given":
            given = mar.actual_datetime or mar.scheduled_datetime
            start = min(start, given)
    return start


def _map_target_met(vitals: Iterable[VitalSignRecord], since: datetime, at: datetime) -> bool:
    """Every blood pressure recorded in ``[since, at)`` reaches the MAP target
    and enough of them were recorded."""
    rules = vasoactive_weaning_rules()
    maps = [
        mean_arterial_pressure(v.systolic_bp, v.diastolic_bp)
        for v in vitals
        if since <= v.timestamp < at and v.systolic_bp is not None and v.diastolic_bp is not None
    ]
    return len(maps) >= rules.min_bp_readings and min(maps) >= rules.map_target_mmhg


def stop_weaned_vasoactive_infusions(
    orders: Iterable[Order],
    mars: Iterable[MedicationAdministration],
    vitals: Iterable[VitalSignRecord],
    shock: bool,
    at: datetime,
) -> list[Order]:
    """Stop, at ``at``, every running vasopressor / inotrope infusion when the
    patient is out of ``shock`` (the daily loop's shock physiology), met the
    MAP target over the ``stable_hours`` before ``at``, and no vasoactive drug
    was started in that window; return the stopped orders. A drug re-ordered
    while it runs (a duplicate or rate order) is not a new start: a drug's
    start is the earliest start of its running orders.

    A stopped order gets ``status`` STOPPED and ``end_datetime`` ``at`` (its
    order time when that is later — a dose charted before the order was
    written), so no dose of it is given from then on.
    """
    running = [o for o in orders if o.status == OrderStatus.PLACED and is_vasoactive_infusion(o)]
    if not running or shock:
        return []
    mars = list(mars)
    since = at - timedelta(hours=vasoactive_weaning_rules().stable_hours)
    drug_start: dict[str, datetime] = {}
    for o in running:
        drug = o.drug_id or drug_ref(o.display_name or "")
        start = _started_at(o, mars)
        drug_start[drug] = min(drug_start.get(drug, start), start)
    if any(start > since for start in drug_start.values()):
        return []
    if not _map_target_met(vitals, since, at):
        return []
    for order in running:
        order.status = OrderStatus.STOPPED
        order.end_datetime = max(at, order.ordered_datetime)
    return running


def vasoactive_support_after(orders: Iterable[Order], cutoff: datetime) -> bool:
    """True while a vasopressor / inotrope infusion still runs, or ran after
    ``cutoff`` (ended later than it)."""
    for o in orders:
        if not is_vasoactive_infusion(o):
            continue
        if o.status == OrderStatus.PLACED:
            return True
        if o.status == OrderStatus.STOPPED and o.end_datetime is not None and o.end_datetime > cutoff:
            return True
    return False
