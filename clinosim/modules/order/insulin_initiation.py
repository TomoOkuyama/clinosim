"""The starting basal-insulin dose of an insulin-naive patient (Issues #3462, #3450).

One rule (``reference_data/insulin_initiation.yaml``: units per kg of body
weight, rounded to whole units) shared by every place that starts basal insulin
without a home regimen to continue: the discharge prescription of a DKA stay
and, later, the inpatient conversion to subcutaneous insulin. Deterministic;
draws nothing.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_validated_yaml

__all__ = ["basal_insulin_start_dose", "basal_insulin_start_units", "insulin_initiation_rules"]

_REF = Path(__file__).resolve().parent / "reference_data" / "insulin_initiation.yaml"

# The rule names a `start_dose: {rule: ...}` entry may use.
START_DOSE_RULES = frozenset({"basal_insulin"})


class _Basal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    units_per_kg: float = Field(gt=0)
    route: str
    frequency: str
    unit_label: str


class _Rules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    basal: _Basal
    source: str


@cache
def insulin_initiation_rules() -> _Rules:
    return _Rules.model_validate(load_validated_yaml(_REF, _Rules))


def basal_insulin_start_units(weight_kg: float) -> int:
    """Whole units of basal insulin per day for a patient of ``weight_kg``
    (at least 1)."""
    return max(1, round(weight_kg * insulin_initiation_rules().basal.units_per_kg))


def basal_insulin_start_dose(weight_kg: float) -> dict[str, str]:
    """``{"dose", "route", "frequency"}`` of the starting basal regimen."""
    b = insulin_initiation_rules().basal
    return {
        "dose": f"{basal_insulin_start_units(weight_kg)}{b.unit_label}",
        "route": b.route,
        "frequency": b.frequency,
    }
