"""The absolute amount given for a weight- or BSA-based dose (Issue #2750).

An order may be prescribed per kilogram ("20 mg/kg") or per square metre of
body surface area ("400 mg/m2"); the administration records what was given,
an absolute amount: the per-kg dose x weight, or the per-m2 dose x body
surface area (Mosteller: sqrt(height_cm x weight_kg / 3600)). A rate
("0.5 mg/kg/h", "0.1 mcg/kg/min") is not a dose and has no absolute amount.
A maximum written with the dose ("0.9 mg/kg IV (max 90mg)") caps the amount
(Issue #2991).
"""

from __future__ import annotations

import math
import re

__all__ = [
    "absolute_dose",
    "body_surface_area",
    "is_continuous_infusion",
    "is_one_time_infusion",
    "is_per_body_unit",
]

# Frequency / name markers of a continuous infusion, whose per-kg figure is a
# rate (per minute or hour), not a dose.
_CONTINUOUS_MARKERS = ("DRIP", "CONTINUOUS", "/MIN", "/H")


def is_continuous_infusion(frequency: str, name: str = "") -> bool:
    """Whether an order is a continuous infusion (its dose is a rate)."""
    text = f"{frequency} {name}".upper()
    return any(marker in text for marker in _CONTINUOUS_MARKERS)


# Issue #3043: a dose given as one timed infusion — "IV over 2h", "over
# 20min", "10% bolus then 60min infusion" (alteplase, magnesium sulfate).
_TIMED_INFUSION = re.compile(
    r"\bover\s*\d+(?:\.\d+)?\s*(?:min|minutes?|h|hrs?|hours?)\b|\b\d+\s*min(?:ute)?s?\s+infusion\b",
    re.IGNORECASE,
)
# A repeat or a running rate written next to it: an interval ("q6-8h"), a
# schedule word, as needed, or a duration of a running infusion ("x12-24h").
_REPEATED = re.compile(r"\bq\s*\d|\b(?:daily|bid|tid|qid|prn|weekly)\b|\bx\s*\d", re.IGNORECASE)


def is_one_time_infusion(name: str) -> bool:
    """Whether an order written without a frequency is one timed infusion
    ("Alteplase 100mg IV over 2h"): a timed-infusion phrase, no repeat or
    running-infusion duration, and not a continuous infusion (Issue #3043)."""
    return (
        bool(_TIMED_INFUSION.search(name or ""))
        and not _REPEATED.search(name or "")
        and not is_continuous_infusion("", name)
    )


# Per-unit dose: "<mass unit>/kg" or "<mass unit>/m2", nothing after it.
_PER_UNIT = re.compile(r"^\s*(mg|g|mcg|ug|µg|U|IU|units?)\s*/\s*(kg|m2|m²)\s*$", re.IGNORECASE)


# A written maximum: "max 90mg", "max. 40 mg".
_MAX = re.compile(r"\bmax\.?\s*(\d+(?:\.\d+)?)\s*(mg|g|mcg|ug|µg|U|IU|units?)\b", re.IGNORECASE)


def is_per_body_unit(unit: str) -> bool:
    """Whether ``unit`` is a per-kg / per-m² dose unit ("mg/kg", "mg/m2")."""
    return bool(_PER_UNIT.match(unit or ""))


def body_surface_area(height_cm: float, weight_kg: float) -> float:
    """Body surface area in m² (Mosteller, NEJM 1987;317:1098)."""
    return math.sqrt(max(height_cm, 0.0) * max(weight_kg, 0.0) / 3600.0)


def _rounded(amount: float) -> float:
    """As dispensed: whole units from 10 up, one decimal below."""
    return float(round(amount)) if amount >= 10 else round(amount, 1)


def absolute_dose(
    value: float | None, unit: str, height_cm: float, weight_kg: float, *, text: str = ""
) -> tuple[float, str] | None:
    """``(amount, mass unit)`` given for a per-kg / per-m² dose, else None.

    ``text`` is the written order; a maximum in it in the same unit
    ("max 90mg") caps the amount."""
    m = _PER_UNIT.match(unit or "")
    if value is None or not m or weight_kg <= 0:
        return None
    base, per = m.group(1), m.group(2).lower()
    factor = weight_kg if per == "kg" else body_surface_area(height_cm, weight_kg)
    if factor <= 0:
        return None
    amount = _rounded(float(value) * factor)
    cap = _MAX.search(text or "")
    if cap and cap.group(2).lower() == base.lower():
        amount = min(amount, float(cap.group(1)))
    return amount, base
