"""Antihypertensives held during permissive hypertension (Issue #3557).

A disease protocol's supportive item may carry a structured
``permissive_hypertension`` block (``PermissiveHypertension``: the systolic
limit, the limit once a thrombolytic is ordered, and the window in hours).
The order engine copies it onto the order; ``permissive_windows`` turns the
placed orders into windows, and ``permissive_hold_reason`` returns the hold
reason of a scheduled dose of an antihypertensive that falls in a window while
the latest systolic pressure is below the limit. Values live in
``reference_data/permissive_hypertension_hold.yaml`` and the protocol.
Everything here is RNG-free.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim.codes.drugs import all_drug_ids, drug_classes
from clinosim.datafiles import load_data_yaml
from clinosim.types.encounter import Order, OrderStatus


class PermissiveHypertension(BaseModel):
    """The ``permissive_hypertension`` block of a protocol supportive item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sbp_limit_mmhg: float = Field(gt=0)
    sbp_limit_thrombolysed_mmhg: float = Field(gt=0)
    window_hours: float = Field(gt=0)


class PermissiveHypertensionRules(BaseModel):
    """Schema of ``reference_data/permissive_hypertension_hold.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    held_classes: tuple[str, ...] = Field(min_length=1)
    thrombolytic_classes: tuple[str, ...] = Field(min_length=1)
    reason: str = Field(min_length=1)

    @field_validator("held_classes", "thrombolytic_classes")
    @classmethod
    def _catalog_classes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        known = {c for d in all_drug_ids() for c in drug_classes(d)}
        unknown = sorted(set(v) - known)
        if unknown:
            raise ValueError(f"drug classes {unknown} are not classes of any catalog drug")
        return v

    @field_validator("reason")
    @classmethod
    def _localized_reason(cls, v: str) -> str:
        from clinosim.locale.loader import load_medication_hold_reasons

        if v not in load_medication_hold_reasons():
            raise ValueError(f"reason {v!r} is not in medication_hold_reasons.yaml")
        return v


@functools.cache
def permissive_hypertension_rules() -> PermissiveHypertensionRules:
    """The validated permissive-hypertension hold rules."""
    return PermissiveHypertensionRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "permissive_hypertension_hold.yaml")
    )


class PermissiveWindow(NamedTuple):
    """One permissive-hypertension order: when it runs and its limits."""

    start: datetime
    end: datetime
    sbp_limit_mmhg: float
    sbp_limit_thrombolysed_mmhg: float
    # Times of the thrombolytic orders of the stay (the lower limit applies from then on).
    thrombolysis_times: tuple[datetime, ...]


def permissive_windows(orders: Iterable[Order]) -> tuple[PermissiveWindow, ...]:
    """A window for every placed order that carries a ``permissive_hypertension``
    block, from its order time for ``window_hours``."""
    orders = list(orders)
    thrombolytic = set(permissive_hypertension_rules().thrombolytic_classes)
    lysis = tuple(
        sorted(
            o.ordered_datetime
            for o in orders
            if o.status == OrderStatus.PLACED
            and not (o.display_name or "").startswith("DISCONTINUE:")
            and thrombolytic & set(drug_classes(o.drug_id or o.display_name))
        )
    )
    out: list[PermissiveWindow] = []
    for o in orders:
        if o.status != OrderStatus.PLACED or not o.permissive_hypertension:
            continue
        p = PermissiveHypertension.model_validate(o.permissive_hypertension)
        out.append(
            PermissiveWindow(
                o.ordered_datetime,
                o.ordered_datetime + timedelta(hours=p.window_hours),
                p.sbp_limit_mmhg,
                p.sbp_limit_thrombolysed_mmhg,
                lysis,
            )
        )
    return tuple(out)


def permissive_hold_reason(
    drug: str, at: datetime, systolic_bp: float | None, windows: Iterable[PermissiveWindow]
) -> str | None:
    """The hold reason of a dose of ``drug`` scheduled at ``at`` when it is in
    ``held_classes``, ``at`` is in a permissive window and the latest systolic
    pressure is below the window's limit (the thrombolysed limit once a
    thrombolytic was ordered), else None. No pressure, no hold."""
    rules = permissive_hypertension_rules()
    if systolic_bp is None or not set(rules.held_classes) & set(drug_classes(drug)):
        return None
    for w in windows:
        if not w.start <= at < w.end:
            continue
        limit = w.sbp_limit_thrombolysed_mmhg if any(t <= at for t in w.thrombolysis_times) else w.sbp_limit_mmhg
        if systolic_bp < limit:
            return rules.reason
    return None
