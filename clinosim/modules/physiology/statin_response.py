"""LDL lowering by statin intensity and by non-statin add-ons (Issues #2917, #2947).

The statin a patient takes, at its dose, has an intensity (2018 ACC/AHA
cholesterol guideline, Table 3), and the intensity lowers the untreated LDL by
a fraction within the guideline's range. A non-statin LDL-lowering drug
(ezetimibe) removes a further fraction of what the statin leaves, from its own
range with or without a statin (Issue #2947). Where in each range a patient
falls is one deterministic per-patient quantile, so it draws no randomness.
Data: ``reference_data/statin_ldl_response.yaml``.

``ldl_reduction`` (statins and add-ons together) is read through
``engine.medication_flags_from_context`` and applied by ``statin_treated_ldl``
in ``engine.lipid_panel``, the lipid panel of both the encounter labs and the
health checkup (``engine.patient_lipid_panel``, Issues #2928, #2941), so one
lipid-lowering model sets both the encounter and the checkup LDL.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim import determinism
from clinosim.codes.drugs import all_drug_ids, drug_classes, drug_ref, find_drug
from clinosim.datafiles import load_data_yaml

_YAML = Path(__file__).resolve().parent / "reference_data" / "statin_ldl_response.yaml"
_STATIN_CLASS = "statin"
_DOSE_MG = re.compile(r"(\d+(?:\.\d+)?)\s*mg\b", re.IGNORECASE)

# Lowest LDL (mg/dL) a statin brings the untreated LDL down to.
STATIN_TREATED_LDL_FLOOR = 30.0

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


def _fraction_range(name: str, value: tuple[float, float]) -> None:
    lo, hi = value
    if not 0.0 <= lo <= hi < 1.0:
        raise ValueError(f"{name} must be an ordered range in [0, 1)")


class _AddOn(BaseModel):
    """LDL fraction a non-statin drug class removes, alone and on top of a
    statin (applied to the LDL the statin leaves)."""

    model_config = ConfigDict(extra="forbid")

    monotherapy: tuple[float, float]
    with_statin: tuple[float, float]


class StatinLdlResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intensity: dict[str, _Bands] = Field(min_length=1)
    default_intensity: Intensity
    ldl_reduction: dict[Intensity, tuple[float, float]]
    add_on: dict[str, _AddOn] = Field(default_factory=dict)

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
        catalog_classes = {cls for drug_id in all_drug_ids() for cls in drug_classes(drug_id)}
        for drug_class, add_on in self.add_on.items():
            if drug_class == _STATIN_CLASS or drug_class not in catalog_classes:
                raise ValueError(f"add_on: {drug_class!r} is not a catalog non-statin drug class")
            _fraction_range(f"add_on[{drug_class}].monotherapy", add_on.monotherapy)
            _fraction_range(f"add_on[{drug_class}].with_statin", add_on.with_statin)
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


def _response_quantile(patient_id: str) -> float:
    """The patient's one position in every LDL-lowering range (a good statin
    responder is a good responder to an add-on too)."""
    return determinism.sha_quantile(f"statin-ldl-response|{patient_id}")


def statin_ldl_reduction(patient_id: str, medications: list[Any]) -> float:
    """Fraction of the untreated LDL removed by the most intense statin in
    ``medications`` (0.0 without a statin). The patient's position in the
    intensity's range is ``determinism.sha_quantile`` of ``patient_id``."""
    levels = [level for level in map(statin_intensity, medications) if level is not None]
    if not levels:
        return 0.0
    level = max(levels, key=_ORDER.index)
    lo, hi = statin_ldl_response().ldl_reduction[level]
    return lo + (hi - lo) * _response_quantile(patient_id)


def ldl_reduction(patient_id: str, medications: list[Any]) -> float:
    """Fraction of the untreated LDL removed by every LDL-lowering drug in
    ``medications`` (Issue #2947): the statin's :func:`statin_ldl_reduction`,
    then each ``add_on`` drug class present (ezetimibe) removing its fraction
    of the LDL left, from its ``with_statin`` range on a statin, else its
    ``monotherapy`` range. 0.0 without any. Same per-patient position as the
    statin; draws no randomness."""
    statin = statin_ldl_reduction(patient_id, medications)
    classes = {cls for med in medications for cls in drug_classes(_drug_id(med))}
    add_ons = [add_on for drug_class, add_on in statin_ldl_response().add_on.items() if drug_class in classes]
    if not add_ons:
        return statin  # the statin's own value, bit for bit
    remaining = 1.0 - statin
    q = _response_quantile(patient_id)
    for add_on in add_ons:
        lo, hi = add_on.with_statin if statin > 0.0 else add_on.monotherapy
        remaining *= 1.0 - (lo + (hi - lo) * q)
    return 1.0 - remaining


def statin_treated_ldl(untreated_ldl: float, reduction: float) -> float:
    """The LDL (mg/dL) after the lipid-lowering drugs remove ``reduction``
    (from :func:`ldl_reduction`) of ``untreated_ldl``; unchanged at 0.0."""
    if reduction <= 0.0:
        return untreated_ldl
    return max(STATIN_TREATED_LDL_FLOOR, untreated_ldl * (1.0 - reduction))
