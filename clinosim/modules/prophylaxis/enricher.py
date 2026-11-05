"""POST_ENCOUNTER enricher: emit DVT prophylaxis order for IMP encounters ≥ 48 h.

Order 75 — after ``device`` (70), before ``hai`` (80). Runs per-record.

Determinism: no RNG. Skip decision is a pure function of state; the emitted
Order is deterministic given the encounter admission_datetime.

Issue #2607: the order's administrations (daily at ``administration_hour``
until discharge, by a nurse of the encounter's ward) are added with it.

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
    for record in records:
        try:
            new_orders = build_dvt_prophylaxis_orders(record=record)
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
        _administer(record, new_orders, getattr(ctx, "roster", None))


def _administer(record: Any, orders: list[Any], roster: Any) -> None:
    """Give the prophylaxis daily from the order until discharge (Issue #2607)."""
    from clinosim.modules.order.placed_order_mar import administrations_for, daily_times, stable_nurse
    from clinosim.modules.prophylaxis.engine import _dvt_rule

    enc = (getattr(record, "encounters", None) or [None])[0]
    discharge = getattr(enc, "discharge_datetime", None) if enc is not None else None
    if discharge is None:
        return
    hour = int(_dvt_rule().get("administration_hour", 21))
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
        mars.extend(administrations_for(order, daily_times(order.ordered_datetime, discharge, hour), nurse))
