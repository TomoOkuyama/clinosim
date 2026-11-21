"""Renal dose selection for VTE prophylaxis (Issue #3449).

Pure functions, no RNG. The constants (equation terms, the CrCl threshold, the
reduced dose) live in ``reference_data/prophylaxis_rules.yaml``; the callers
pass them in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clinosim.modules.observation.engine import canonical_lab_name

_CREATININE = "Creatinine"


def crcl_cockcroft_gault(
    creatinine_mg_dl: float,
    age_years: float,
    weight_kg: float,
    sex: str,
    *,
    age_offset: float,
    denominator: float,
    female_factor: float,
) -> float:
    """Creatinine clearance (mL/min) by the Cockcroft-Gault equation:
    ``(age_offset - age) x weight / (denominator x creatinine)``, times
    ``female_factor`` for a female patient."""
    crcl = (age_offset - age_years) * weight_kg / (denominator * creatinine_mg_dl)
    return crcl * female_factor if str(sex or "").upper().startswith("F") else crcl


def creatinine_series(record: Any, unit: str) -> list[tuple[datetime, float]]:
    """The record's resulted creatinine values in ``unit``, oldest first (a result
    without a time, a value or in another unit is left out)."""
    found: set[tuple[datetime, float]] = set()
    results = list(getattr(record, "lab_results", None) or [])
    results += [getattr(o, "result", None) for o in (getattr(record, "orders", None) or [])]
    for res in results:
        if res is None:
            continue
        when = getattr(res, "result_datetime", None)
        value = getattr(res, "value", None)
        res_unit = getattr(res, "unit", None)
        if (
            isinstance(when, datetime)
            and isinstance(value, (int, float))
            and value > 0
            and (res_unit in (None, "", unit))
            and canonical_lab_name(str(getattr(res, "lab_name", "") or "")) == _CREATININE
        ):
            found.add((when, float(value)))
    return sorted(found)


def dose_periods(
    series: list[tuple[datetime, float]],
    *,
    start: datetime,
    end: datetime,
    crcl_of: Any,
    crcl_below: float,
) -> list[tuple[datetime, bool]]:
    """``[(from, reduced), ...]``: when each dose tier begins over ``start`` to ``end``.

    The tier at ``start`` follows the latest result at or before it (the standard
    dose with none). The dose is reduced once and stays reduced: the first result
    after ``start`` with a clearance below ``crcl_below`` starts the reduced tier
    at its result time (a dose is not stepped back up on a noisy later value).
    ``crcl_of(creatinine)`` gives the clearance, or None when it cannot be
    computed (the standard tier)."""

    def reduced(creatinine: float) -> bool:
        crcl = crcl_of(creatinine)
        return crcl is not None and crcl < crcl_below

    prior = [v for t, v in series if t <= start]
    if prior and reduced(prior[-1]):
        return [(start, True)]
    for when, value in series:
        if start < when < end and reduced(value):
            return [(start, False), (when, True)]
    return [(start, False)]
