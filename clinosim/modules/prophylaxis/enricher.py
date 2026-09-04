"""POST_ENCOUNTER enricher: emit DVT prophylaxis order for IMP encounters ≥ 48 h.

Order 75 — after ``device`` (70), before ``hai`` (80). Runs per-record.

Determinism: no RNG. Skip decision is a pure function of state; the emitted
Order is deterministic given the encounter admission_datetime.

RNG-preservation: this enricher does NOT consume master RNG. It touches only
its own per-patient sub-RNG (currently unused because the emission is
deterministic; kept as a future-proofing hook for dose jitter / adherence
sampling).
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
            record.orders = list(new_orders)  # type: ignore[attr-defined]
        else:
            existing.extend(new_orders)
