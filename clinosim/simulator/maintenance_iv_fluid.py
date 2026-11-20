"""Stopping the maintenance IV-fluid order of an admission (Issue #3409).

The admission ``IV_fluid`` supportive order (for example "NS 125 mL/h") ends
once the patient is on an oral diet (after a grace period) or after a maximum
number of days (``reference_data/maintenance_iv_fluid.yaml``). A stopped order
gets ``status`` STOPPED and ``end_datetime``, so the MAR gives no dose of it
from then on, and the day's I/O record carries no maintenance IV intake.
Everything here is RNG-free.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml
from clinosim.types.encounter import Order, OrderStatus, OrderType


class MaintenanceIVFluidRules(BaseModel):
    """Schema of ``reference_data/maintenance_iv_fluid.yaml`` (Issue #3409)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    oral_diets: tuple[str, ...] = Field(min_length=1)
    grace_days: int = Field(ge=0)
    max_days: int = Field(ge=1)
    oral_intake_mean_ml_after_stop: float = Field(gt=0)
    oral_intake_sd_ml_after_stop: float = Field(ge=0)
    order_display_prefix: str = Field(min_length=1)
    excluded_detail_markers: tuple[str, ...]


@functools.cache
def maintenance_iv_fluid_rules() -> MaintenanceIVFluidRules:
    """The validated maintenance IV-fluid stop rules."""
    return MaintenanceIVFluidRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "maintenance_iv_fluid.yaml")
    )


def is_maintenance_iv_fluid_name(name: str) -> bool:
    """Whether the order display name ``name`` ("IV_fluid: NS 125 mL/h") is a
    maintenance IV fluid (not a bolus or a titrated / resuscitation regimen)."""
    rules = maintenance_iv_fluid_rules()
    if not name.startswith(rules.order_display_prefix):
        return False
    detail = name[len(rules.order_display_prefix) :].lower()
    return not any(marker.lower() in detail for marker in rules.excluded_detail_markers)


def is_maintenance_iv_fluid(order: Order) -> bool:
    """Whether ``order`` is a maintenance IV-fluid order (not a bolus or a
    titrated / resuscitation regimen)."""
    return order.order_type == OrderType.MEDICATION and is_maintenance_iv_fluid_name(order.display_name or "")


def stop_maintenance_iv_fluid(
    orders: Iterable[Order], day: int, oral_diet_since_day: int | None, day_start: datetime
) -> list[Order]:
    """Stop, at ``day_start`` (the start of hospital day ``day``), every running
    maintenance IV-fluid order when the diet has been oral for ``grace_days``
    days (``oral_diet_since_day``: the day the diet first reached an oral diet,
    None while it has not) or ``day`` reached ``max_days``; return the stopped
    orders."""
    rules = maintenance_iv_fluid_rules()
    oral_done = oral_diet_since_day is not None and day - oral_diet_since_day >= rules.grace_days
    if not (oral_done or day >= rules.max_days):
        return []
    running = [o for o in orders if o.status == OrderStatus.PLACED and is_maintenance_iv_fluid(o)]
    for order in running:
        order.status = OrderStatus.STOPPED
        order.end_datetime = max(day_start, order.ordered_datetime)
    return running


def maintenance_iv_fluid_stopped(orders: Iterable[Order], at: datetime) -> bool:
    """Whether a maintenance IV-fluid order was stopped at or before ``at``."""
    return any(
        o.status == OrderStatus.STOPPED
        and o.end_datetime is not None
        and o.end_datetime <= at
        and is_maintenance_iv_fluid(o)
        for o in orders
    )
