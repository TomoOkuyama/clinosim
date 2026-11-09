"""Weight-based doses of ED orders for children (Issue #2857, #2977).

ED protocols write adult fixed strengths ("Acetaminophen 500mg") and fixed
fluid boluses ("IV normal saline 1000mL"). For a patient under
``adult_age_years`` a listed drug is re-dosed from the weight
(``pediatric_dosing.yaml``) and not given below its minimum age; a listed
fluid's bolus becomes ``ml_per_kg`` × weight, never more than the written
adult volume.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim.codes.drugs import drug_key
from clinosim.datafiles import load_validated_yaml

_REF = Path(__file__).resolve().parent / "reference_data" / "pediatric_dosing.yaml"
_STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*mg\b", re.IGNORECASE)
_VOLUME = re.compile(r"(\d+(?:\.\d+)?)\s*(mL|L)\b", re.IGNORECASE)


class _PediatricDose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mg_per_kg: float = Field(gt=0)
    max_mg: float = Field(gt=0)
    min_age_months: int = Field(ge=0)


class _PediatricFluid(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ml_per_kg: float = Field(gt=0)


class PediatricDosingFile(BaseModel):
    """Shape of ``pediatric_dosing.yaml``."""

    model_config = ConfigDict(extra="forbid")
    adult_age_years: int = Field(gt=0)
    drugs: dict[str, _PediatricDose]
    fluids: dict[str, _PediatricFluid] = Field(default_factory=dict)


@cache
def _table() -> dict[str, Any]:
    return load_validated_yaml(_REF, PediatricDosingFile)


def _rounded(mg: float) -> str:
    if mg < 10:
        return f"{round(mg, 1):g}"
    return str(int(round(mg)))


def _fluid_bolus_name(name: str, ml_per_kg: float, weight_kg: float | None) -> str:
    """``name`` with its bolus volume re-sized to ``ml_per_kg`` × weight (whole
    mL), capped at the written volume; unchanged without a volume or weight."""
    m = _VOLUME.search(name)
    if not m or not weight_kg or weight_kg <= 0:
        return name
    written_ml = float(m.group(1)) * (1000.0 if m.group(2).lower() == "l" else 1.0)
    ml = min(round(ml_per_kg * float(weight_kg)), written_ml)
    return name[: m.start()] + f"{ml:g}mL" + name[m.end() :]


def pediatric_order_name(name: str, age_months: int, weight_kg: float | None) -> str | None:
    """``name`` re-dosed for a child, unchanged for an adult or an unlisted drug,
    or None when the child is below the drug's minimum age."""
    table = _table()
    if age_months >= int(table["adult_age_years"]) * 12:
        return name
    key = drug_key(name)
    fluid = (table.get("fluids") or {}).get(key)
    if fluid is not None:
        return _fluid_bolus_name(name, float(fluid["ml_per_kg"]), weight_kg)
    rule = table["drugs"].get(key)
    if rule is None:
        return name
    if age_months < int(rule["min_age_months"]):
        return None
    if not weight_kg or weight_kg <= 0 or not _STRENGTH.search(name):
        return name
    mg = min(float(rule["mg_per_kg"]) * float(weight_kg), float(rule["max_mg"]))
    return _STRENGTH.sub(f"{_rounded(mg)}mg", name, count=1)
