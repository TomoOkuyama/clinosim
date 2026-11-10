"""Per-country label dose limits of oral take-home and ED drugs (Issue #3012).

Protocol YAMLs write one regimen for every country ("Ibuprofen 600mg" three
times daily). Where a country's package insert allows less — Japanese
ibuprofen (ブルフェン) is 200 mg three times daily, 600 mg/day — the written
regimen is brought within that label (``label_dose_limits.yaml``).
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim.codes.drugs import drug_ref, get_drug
from clinosim.countries import country_code
from clinosim.country_profile import supported_countries
from clinosim.datafiles import load_data_yaml

_REF = Path(__file__).resolve().parent / "reference_data" / "label_dose_limits.yaml"
_STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*mg\b", re.IGNORECASE)
_INTERVAL = re.compile(r"^q(\d+)(?:\s*-\s*\d+)?\s*h$")
_PRN_SUFFIX = re.compile(r"\s+(prn|as needed)$", re.IGNORECASE)
# Frequency label written for N doses a day when a regimen is reduced.
_PER_DAY_LABEL = {1: "daily", 2: "bid", 3: "tid", 4: "qid"}


class _Limit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dose_mg: float = Field(gt=0)
    max_doses_per_day: int = Field(ge=1, le=4)
    max_mg_per_day: float = Field(gt=0)


class LabelDoseLimitsFile(BaseModel):
    """Shape of ``label_dose_limits.yaml``."""

    model_config = ConfigDict(extra="forbid")
    limits: dict[str, dict[str, _Limit]]

    @field_validator("limits")
    @classmethod
    def _keys(cls, v: dict[str, dict[str, _Limit]]) -> dict[str, dict[str, _Limit]]:
        for cc, drugs in v.items():
            if cc not in supported_countries():
                raise ValueError(f"country {cc!r} is not a supported upper-case country code")
            for drug_id in drugs:
                if get_drug(drug_id) is None:
                    raise ValueError(f"drug_id {drug_id!r} is not in the drug catalog")
        return v


@cache
def _limits() -> LabelDoseLimitsFile:
    return LabelDoseLimitsFile.model_validate(load_data_yaml(_REF))


def doses_per_day(frequency: str) -> int:
    """Most doses a day a frequency label allows ("tid" 3, "q6h PRN" 4,
    "q4-6h" 6); 1 for a one-time or unknown label."""
    from clinosim.modules.order.engine import _freq_per_day

    label = _PRN_SUFFIX.sub("", " ".join((frequency or "").lower().split()))
    if m := _INTERVAL.match(label):
        return max(1, 24 // int(m.group(1)))
    return _freq_per_day().get(label, 1)


def within_label(name: str, frequency: str, country: str) -> tuple[str, str]:
    """``(name, frequency)`` of a written regimen ("Ibuprofen 600mg", "tid")
    brought within the country's label: the single dose in ``name`` lowered
    to the label dose, and the number of doses a day lowered (a PRN regimen
    stays PRN) when the daily total is still above the label maximum.
    Unchanged for a drug the country does not limit."""
    limit = _limits().limits.get(country_code(country), {}).get(drug_ref(name))
    m = _STRENGTH.search(name)
    if limit is None or m is None:
        return name, frequency
    dose = min(float(m.group(1)), limit.dose_mg)
    if dose < float(m.group(1)):
        name = _STRENGTH.sub(f"{dose:g}mg", name, count=1)
    if dose * doses_per_day(frequency) > limit.max_mg_per_day:
        n = min(limit.max_doses_per_day, int(limit.max_mg_per_day // dose))
        prn = _PRN_SUFFIX.search(frequency.strip())
        frequency = _PER_DAY_LABEL[n] + (f" {prn.group(1)}" if prn else "")
    return name, frequency
