"""Weight-based doses of ED orders for children (Issue #2857).

ED protocols write adult fixed strengths ("Acetaminophen 500mg"). For a patient
under ``adult_age_years`` a listed drug is re-dosed from the weight
(``pediatric_dosing.yaml``) and not given below its minimum age.
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


class _PediatricDose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mg_per_kg: float = Field(gt=0)
    max_mg: float = Field(gt=0)
    min_age_months: int = Field(ge=0)


class PediatricDosingFile(BaseModel):
    """Shape of ``pediatric_dosing.yaml``."""

    model_config = ConfigDict(extra="forbid")
    adult_age_years: int = Field(gt=0)
    drugs: dict[str, _PediatricDose]


@cache
def _table() -> dict[str, Any]:
    return load_validated_yaml(_REF, PediatricDosingFile)


def _rounded(mg: float) -> str:
    if mg < 10:
        return f"{round(mg, 1):g}"
    return str(int(round(mg)))


def pediatric_order_name(name: str, age_months: int, weight_kg: float | None) -> str | None:
    """``name`` re-dosed for a child, unchanged for an adult or an unlisted drug,
    or None when the child is below the drug's minimum age."""
    table = _table()
    if age_months >= int(table["adult_age_years"]) * 12:
        return name
    rule = table["drugs"].get(drug_key(name))
    if rule is None:
        return name
    if age_months < int(rule["min_age_months"]):
        return None
    if not weight_kg or weight_kg <= 0 or not _STRENGTH.search(name):
        return name
    mg = min(float(rule["mg_per_kg"]) * float(weight_kg), float(rule["max_mg"]))
    return _STRENGTH.sub(f"{_rounded(mg)}mg", name, count=1)
