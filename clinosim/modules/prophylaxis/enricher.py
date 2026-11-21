"""POST_ENCOUNTER enricher: emit DVT prophylaxis order for IMP encounters ≥ 48 h.

Order 75 — after ``device`` (70), before ``hai`` (80). Runs per-record.

Determinism: no RNG. Skip decision is a pure function of state; the emitted
Order is deterministic given the encounter admission_datetime.

Issue #2607: the order's administrations (at the regimen's
``administration_hours`` every day until discharge, or until the order that
replaces it, by a nurse of the encounter's ward) are added with it.
Issue #3449: the regimen follows ``ctx.config.country`` and the renal function.

RNG-preservation: this enricher draws from no RNG at all — neither the
master RNG nor a sub-RNG (``ENRICHER_SEED_OFFSETS["prophylaxis"]`` is
reserved but unused).
"""

from __future__ import annotations

import logging
from typing import Any

from clinosim.modules.prophylaxis.engine import build_dvt_prophylaxis_orders

logger = logging.getLogger(__name__)


def enrich_prophylaxis(ctx: Any) -> None:
    """POST_ENCOUNTER enricher entrypoint.

    Walks ``ctx.records`` and, for each IMP record with LOS ≥ 48 h that
    is not on therapeutic anticoagulation and does not carry a
    bleeding / delivery / active-DVT contraindication, appends a
    DVT prophylaxis Order to ``record.orders``.
    """
    records = getattr(ctx, "records", None) or []
    country = str(getattr(getattr(ctx, "config", None), "country", "") or "")
    for record in records:
        try:
            new_orders = build_dvt_prophylaxis_orders(record=record, country=country)
        except Exception:  # pragma: no cover — defensive
            logger.exception("prophylaxis enricher failed on record; continuing")
            continue
        if not new_orders:
            continue
        existing = getattr(record, "orders", None)
        if existing is None:
            record.orders = list(new_orders)
        else:
            existing.extend(new_orders)
        _administer(record, new_orders, getattr(ctx, "roster", None), country)


def _administer(record: Any, orders: list[Any], roster: Any, country: str) -> None:
    """Give the prophylaxis at the regimen's times from each order until the
    order that replaces it, or discharge (Issues #2607, #3449)."""
    from clinosim.modules.order.placed_order_mar import administrations_for, daily_times, stable_nurse
    from clinosim.modules.prophylaxis.engine import dvt_regimen

    enc = (getattr(record, "encounters", None) or [None])[0]
    discharge = getattr(enc, "discharge_datetime", None) if enc is not None else None
    if discharge is None:
        return
    hours = dvt_regimen(country)["administration_hours"]
    mars = getattr(record, "medication_administrations", None)
    if mars is None:
        mars = []
        record.medication_administrations = mars
    for order in orders:
        nurse = stable_nurse(
            roster,
            order.order_id,
            ward=str(getattr(enc, "ward_id", "") or ""),
            department=str(getattr(enc, "department_id", "") or ""),
        )
        until = order.end_datetime or discharge
        times = sorted(t for hour in hours for t in daily_times(order.ordered_datetime, until, int(hour)))
        mars.extend(administrations_for(order, times, nurse))
