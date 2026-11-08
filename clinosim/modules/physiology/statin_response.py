"""LDL lowering by statin intensity (Issue #2917).

The statin a patient takes, at its dose, has an intensity (2018 ACC/AHA
cholesterol guideline, Table 3), and the intensity lowers the untreated LDL by
a fraction within the guideline's range; where in the range a patient falls is
a deterministic per-patient quantile, so it draws no randomness. Data:
``reference_data/statin_ldl_response.yaml``.

``statin_ldl_reduction`` is read through
``engine.medication_flags_from_context`` and applied by
``engine._add_lipid_labs``.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim import determinism
from clinosim.codes.drugs import drug_classes, drug_ref, find_drug
from clinosim.datafiles import load_data_yaml

_YAML = Path(__file__).resolve().parent / "reference_data" / "statin_ldl_response.yaml"
_STATIN_CLASS = "statin"
_DOSE_MG = re.compile(r"(\d+(?:\.\d+)?)\s*mg\b", re.IGNORECASE)

Intensity = Literal["low", "moderate", "high"]
_ORDER: tuple[Intensity, ...] = ("low", "moderate", "high")


class _Bands(BaseModel):
    """Lowest daily dose (mg) of each intensity of one statin."""

    model_config = ConfigDict(extra="forbid")

    moderate: float | None = Field(default=None, gt=0)
    high: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> _Bands:
        if self.moderate is None and self.high is None:
            raise ValueError("intensity: a statin needs a moderate or high dose")
        if self.moderate is not None and self.high is not None and self.high <= self.moderate:
            raise ValueError("intensity: the high dose must be above the moderate dose")
        return self


class StatinLdlResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intensity: dict[str, _Bands] = Field(min_length=1)
    default_intensity: Intensity
    ldl_reduction: dict[Intensity, tuple[float, float]]

    @model_validator(mode="after")
    def _check(self) -> StatinLdlResponse:
        for drug_id in self.intensity:
            if find_drug(drug_id) is None or _STATIN_CLASS not in drug_classes(drug_id):
                raise ValueError(f"intensity: {drug_id!r} is not a catalog statin")
        if set(self.ldl_reduction) != set(_ORDER):
            raise ValueError(f"ldl_reduction must list {list(_ORDER)}")
        previous_high = 0.0
        for level in _ORDER:
            lo, hi = self.ldl_reduction[level]
            if not 0.0 <= lo <= hi < 1.0 or lo < previous_high:
                raise ValueError(f"ldl_reduction[{level}] must be an ordered range in [0, 1) above the lower intensity")
            previous_high = hi
        return self


@functools.cache
def statin_ldl_response() -> StatinLdlResponse:
    """The validated ``statin_ldl_response.yaml`` (shared, read-only)."""
    return StatinLdlResponse.model_validate(load_data_yaml(_YAML))


def _field(med: Any, name: str) -> str:
    value = med.get(name) if isinstance(med, dict) else getattr(med, name, None)
    return str(value or "")


def _drug_id(med: Any) -> str:
    if isinstance(med, str):
        return drug_ref(med)
    return _field(med, "drug_id") or drug_ref(_field(med, "drug_name"))


def statin_intensity(med: Any) -> Intensity | None:
    """Intensity of ``med`` (a home medication, an order, a dict or a drug
    name) when it is a statin, else ``None``."""
    drug_id = _drug_id(med)
    if not drug_id or _STATIN_CLASS not in drug_classes(drug_id):
        return None
    data = statin_ldl_response()
    bands = data.intensity.get(drug_id)
    # The dose field, else a dose written into the drug name ("Atorvastatin 40mg").
    text = med if isinstance(med, str) else _field(med, "dose") or _field(med, "drug_name")
    match = _DOSE_MG.search(text)
    if bands is None or match is None:
        return data.default_intensity
    mg = float(match.group(1))
    if bands.high is not None and mg >= bands.high:
        return "high"
    if bands.moderate is not None and mg >= bands.moderate:
        return "moderate"
    return "low"


def statin_ldl_reduction(patient_id: str, medications: list[Any]) -> float:
    """Fraction of the untreated LDL removed by the most intense statin in
    ``medications`` (0.0 without a statin). The patient's position in the
    intensity's range is ``determinism.sha_quantile`` of ``patient_id``."""
    levels = [level for level in map(statin_intensity, medications) if level is not None]
    if not levels:
        return 0.0
    level = max(levels, key=_ORDER.index)
    lo, hi = statin_ldl_response().ldl_reduction[level]
    return lo + (hi - lo) * determinism.sha_quantile(f"statin-ldl-response|{patient_id}")
