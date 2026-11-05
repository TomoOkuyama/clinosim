"""Administrations for orders placed outside the daily MAR loop (Issue #2607).

The daily loop writes the MAR of the orders it places. Orders added after it
(the VTE prophylaxis enricher) or by a pathway with its own timeline (the
delivery bundle) had none, so their MedicationRequests were active with no
administration. These helpers build those administrations deterministically
(no RNG): fixed times and a stable nurse.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from clinosim.types.encounter import MedicationAdministration


def daily_times(start: datetime, end: datetime, hour: int) -> list[datetime]:
    """Every ``hour``:00 from the first one at or after ``start`` up to (not including) ``end``."""
    first = start.replace(hour=hour, minute=0, second=0, microsecond=0)
    if first < start:
        first += timedelta(days=1)
    out = []
    while first < end:
        out.append(first)
        first += timedelta(days=1)
    return out


def stable_nurse(roster: Any, key: str, *, ward: str = "", department: str = "") -> str:
    """A nurse of the ward / department, picked stably by ``key`` (no RNG)."""
    if roster is None or not getattr(roster, "members", None):
        return ""
    from clinosim.modules.staff.engine import scoped_nurses

    nurses = sorted(m.staff_id for m in scoped_nurses(roster, ward=ward, department=department))
    return nurses[sum(ord(c) for c in key) % len(nurses)] if nurses else ""


def administrations_for(order: Any, times: list[datetime], nurse_id: str) -> list[MedicationAdministration]:
    """One given administration of ``order`` at each of ``times``."""
    if order.dose_quantity is not None and order.dose_unit:
        dose = f"{order.dose_quantity}{order.dose_unit}" + (f" {order.frequency}" if order.frequency else "")
    else:
        dose = order.display_name
    return [
        MedicationAdministration(
            order_id=order.order_id,
            drug_name=order.display_name,
            scheduled_datetime=t,
            actual_datetime=t,
            status="given",
            dose=dose,
            route=order.route,
            administered_by=nurse_id,
        )
        for t in times
    ]
