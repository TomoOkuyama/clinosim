"""When an outpatient order is placed inside its visit (Issue #3918)."""

from __future__ import annotations

import functools
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml
from clinosim.simulator._outpatient_thresholds import OUTPATIENT_LAB_ORDER_OFFSET_MIN

__all__ = ["OutpatientOrderTiming", "outpatient_order_time", "outpatient_order_timing"]


class OutpatientOrderTiming(BaseModel):
    """Schema of ``reference_data/outpatient_order_timing.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_fraction_of_visit: float = Field(gt=0, lt=1)


@functools.cache
def outpatient_order_timing() -> OutpatientOrderTiming:
    """The validated outpatient order-timing rules."""
    return OutpatientOrderTiming.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "outpatient_order_timing.yaml")
    )


def outpatient_order_time(visit_start: datetime, visit_end: datetime | None) -> datetime:
    """The time an order of an outpatient visit is placed.

    The smaller of the fixed offset after the visit start and the configured
    fraction of the visit length; the fixed offset when the visit has no
    known end.
    """
    offset = timedelta(minutes=OUTPATIENT_LAB_ORDER_OFFSET_MIN)
    if not isinstance(visit_end, datetime) or visit_end <= visit_start:
        return visit_start + offset
    capped = (visit_end - visit_start) * outpatient_order_timing().max_fraction_of_visit
    return (visit_start + min(offset, capped)).replace(microsecond=0)
