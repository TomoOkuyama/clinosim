"""Weight-based doses for children (Issue #2857, #2977, #3004).

Protocols write adult fixed strengths ("Acetaminophen 500mg"), fixed fluid
boluses ("IV normal saline 1000mL") and adult maintenance rates ("NS 80-125
mL/h"). For a patient under ``adult_age_years`` (``pediatric_dosing.yaml``):

- ED orders and take-home prescriptions (``pediatric_order_name``): a listed
  drug is re-dosed from the weight and not given below its minimum age; a
  listed fluid's bolus becomes ``ml_per_kg`` × weight, never more than the
  written adult volume.
- Inpatient orders and discharge prescriptions (``redose_order_for_child``,
  ``pediatric_dose_text``, Issue #3004): a listed drug's mg dose becomes
  ``mg_per_kg`` × weight and a listed fluid's maintenance rate the
  Holliday-Segar rate, never more than the written adult dose or rate.
  Antibiotics are listed too, and a dose written in grams is re-dosed in mg
  (Issue #3082); the antibiotic enricher's regimens use the same table.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim.codes.drugs import drug_key
from clinosim.countries import country_code
from clinosim.datafiles import load_validated_yaml

_REF = Path(__file__).resolve().parent / "reference_data" / "pediatric_dosing.yaml"
_STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*mg\b", re.IGNORECASE)
# A strength in milligrams or grams ("1g", "3.375 g", "500mg"); grams are how
# the adult antibiotic regimens are written (Issue #3082).
_MG_OR_G = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|g)\b", re.IGNORECASE)
_MG_PER_UNIT = {"mg": 1.0, "g": 1000.0}
_VOLUME = re.compile(r"(\d+(?:\.\d+)?)\s*(mL|L)\b", re.IGNORECASE)
# An hourly rate as written, a range ("80-125 mL/h") or one value.
# A written dosing interval ("q6h"), replaced by a neonatal band's (Issue #3063).
_INTERVAL = re.compile(r"\bq\d+h\b", re.IGNORECASE)
_RATE = re.compile(r"\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?\s*mL/h\b", re.IGNORECASE)


class _PediatricDose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mg_per_kg: float = Field(gt=0)
    max_mg: float = Field(gt=0)
    min_age_months: int = Field(ge=0)


class _PediatricFluid(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ml_per_kg: float = Field(gt=0)


class _NeonatalBand(BaseModel):
    """A neonatal dose up to a postnatal age (Issue #3063)."""

    model_config = ConfigDict(extra="forbid")
    max_postnatal_age_days: int = Field(ge=0)
    mg_per_kg: float = Field(gt=0)
    interval_hours: int = Field(gt=0)


class _HollidaySegarBand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    up_to_kg: float | None = Field(default=None, gt=0)  # None: every further kg
    ml_per_kg_per_h: float = Field(gt=0)


class PediatricDosingFile(BaseModel):
    """Shape of ``pediatric_dosing.yaml``."""

    model_config = ConfigDict(extra="forbid")
    adult_age_years: int = Field(gt=0)
    drugs: dict[str, _PediatricDose]
    fluids: dict[str, _PediatricFluid] = Field(default_factory=dict)
    # Upper-case country code -> drug -> rule replacing ``drugs`` (Issue #3012).
    country_overrides: dict[str, dict[str, _PediatricDose]] = Field(default_factory=dict)
    maintenance_fluid_bands: list[_HollidaySegarBand] = Field(min_length=1)
    # Drug -> postnatal-age bands, ascending (Issue #3063).
    neonatal_drugs: dict[str, list[_NeonatalBand]] = Field(default_factory=dict)

    @field_validator("neonatal_drugs")
    @classmethod
    def _ascending(cls, drugs: dict[str, list[_NeonatalBand]]) -> dict[str, list[_NeonatalBand]]:
        for drug, bands in drugs.items():
            ages = [b.max_postnatal_age_days for b in bands]
            if not bands or ages != sorted(set(ages)):
                raise ValueError(
                    f"neonatal_drugs.{drug}: bands must be non-empty and ascending by max_postnatal_age_days"
                )
        return drugs


@cache
def _table() -> dict[str, Any]:
    return load_validated_yaml(_REF, PediatricDosingFile)


def _rounded(mg: float) -> str:
    if mg < 1:  # e.g. epinephrine 0.01 mg/kg, drawn up to 0.01 mg
        return f"{round(mg, 2):g}"
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


def _neonatal_band(key: str, age_days: int | None) -> dict[str, Any] | None:
    """The ``neonatal_drugs`` band of drug ``key`` covering ``age_days`` days
    of life, or None (Issue #3063)."""
    if age_days is None or age_days < 0:
        return None
    for band in (_table().get("neonatal_drugs") or {}).get(key) or []:
        if age_days <= int(band["max_postnatal_age_days"]):
            return dict(band)
    return None


def _drug_rule(key: str, country: str, age_days: int | None = None) -> dict[str, Any] | None:
    """The dosing rule of drug ``key``: in the neonatal period its
    ``neonatal_drugs`` band (no adult cap; Issue #3063), else the country's
    ``country_overrides`` rule, else the shared one (Issue #3012)."""
    band = _neonatal_band(key, age_days)
    if band is not None:
        return {"mg_per_kg": band["mg_per_kg"], "max_mg": float("inf"), "min_age_months": 0}
    table = _table()
    return (table.get("country_overrides") or {}).get(country_code(country), {}).get(key) or table["drugs"].get(key)


def neonatal_interval_hours(name: str, age_days: int | None) -> int | None:
    """Dosing interval (hours) of drug ``name`` for an infant ``age_days``
    days old, or None outside the neonatal bands (Issue #3063)."""
    band = _neonatal_band(drug_key(name), age_days)
    return int(band["interval_hours"]) if band is not None else None


def pediatric_order_name(
    name: str, age_months: int, weight_kg: float | None, country: str, age_days: int | None = None
) -> str | None:
    """``name`` re-dosed for a child, unchanged for an adult or an unlisted drug,
    or None when the child is below the drug's minimum age. A country's
    ``country_overrides`` rule replaces the shared one (Issue #3012); a
    neonate ``age_days`` old gets the drug's neonatal band (Issue #3063)."""
    table = _table()
    if age_months >= int(table["adult_age_years"]) * 12:
        return name
    key = drug_key(name)
    fluid = (table.get("fluids") or {}).get(key)
    if fluid is not None:
        return _fluid_bolus_name(name, float(fluid["ml_per_kg"]), weight_kg)
    rule = _drug_rule(key, country, age_days)
    if rule is None:
        return name
    if age_months < int(rule["min_age_months"]):
        return None
    if not weight_kg or weight_kg <= 0 or not _STRENGTH.search(name):
        return name
    mg = min(float(rule["mg_per_kg"]) * float(weight_kg), float(rule["max_mg"]))
    return _STRENGTH.sub(f"{_rounded(mg)}mg", name, count=1)


def pediatric_adult_age_months() -> int:
    """Age in months from which the adult (written) doses apply."""
    return int(_table()["adult_age_years"]) * 12


def maintenance_fluid_ml_per_h(weight_kg: float) -> int:
    """Hourly maintenance fluid rate (whole mL/h) for ``weight_kg`` by the
    Holliday-Segar rule (``maintenance_fluid_bands``)."""
    rate, below = 0.0, 0.0
    for band in _table()["maintenance_fluid_bands"]:
        top = band.get("up_to_kg")
        kg = max(0.0, (float(weight_kg) if top is None else min(float(weight_kg), float(top))) - below)
        rate += kg * float(band["ml_per_kg_per_h"])
        if top is None or weight_kg <= top:
            break
        below = float(top)
    return int(round(rate))


def _child_mg(
    key: str, written_mg: float, age_months: int, weight_kg: float | None, country: str, age_days: int | None = None
) -> float | None:
    """A child's dose (mg) of drug ``key`` written as ``written_mg`` for an
    adult, or None when it is not re-dosed (adult, unlisted drug, no weight).
    Never more than the written dose."""
    table = _table()
    rule = _drug_rule(key, country, age_days)
    if rule is None or age_months >= int(table["adult_age_years"]) * 12 or not weight_kg or weight_kg <= 0:
        return None
    mg = min(float(rule["mg_per_kg"]) * float(weight_kg), float(rule["max_mg"]), written_mg)
    return float(_rounded(mg))


def pediatric_dose_text(
    drug: str, dose: str, age_months: int, weight_kg: float | None, country: str, age_days: int | None = None
) -> str:
    """A prescription's dose text (``"75mg PO BID"``, ``"1g"``) re-dosed for a
    child (Issue #3004, #3082): its first mg or g strength becomes the child's
    dose in mg; a neonate ``age_days`` old gets the drug's neonatal band (Issue
    #3063). Unchanged for an adult, an unlisted drug, a dose not written in
    mg or g, or a child dose no lower than the written one."""
    m = _MG_OR_G.search(dose or "")
    if not m or (m.end() < len(dose) and dose[m.end()] == "/"):
        return dose
    written = float(m.group(1)) * _MG_PER_UNIT[m.group(2).lower()]
    mg = _child_mg(drug_key(drug), written, age_months, weight_kg, country, age_days)
    if mg is None or (mg >= written and m.group(2).lower() == "g"):
        return dose
    return dose[: m.start()] + f"{mg:g}mg" + dose[m.end() :]


def redose_order_for_child(
    order: Any, age_months: int, weight_kg: float | None, country: str, age_days: int | None = None
) -> None:
    """Re-dose an inpatient medication order for a child in place (Issue
    #3004): a listed drug written in mg gets ``mg_per_kg`` × weight, a listed
    fluid's hourly rate the Holliday-Segar rate, never more than written.
    The written strength in the order's name follows. A neonate ``age_days``
    old gets the drug's neonatal band and its dosing interval (Issue #3063).
    Idempotent; adults, unlisted drugs and per-kg orders are unchanged."""
    table = _table()
    if age_months >= int(table["adult_age_years"]) * 12 or not weight_kg or weight_kg <= 0:
        return
    if order.dose_quantity is None:
        return
    name = order.display_name or ""
    key = drug_key(name) or str(getattr(order, "drug_id", "") or "")
    unit = str(order.dose_unit or "")
    if unit.lower() == "ml/h" and key in (table.get("fluids") or {}):
        rate = float(min(maintenance_fluid_ml_per_h(weight_kg), order.dose_quantity))
        if rate < order.dose_quantity:
            order.dose_quantity = rate
            order.display_name = _RATE.sub(f"{rate:g} mL/h", name, count=1)
        return
    per_unit = _MG_PER_UNIT.get(unit.lower())
    if per_unit is None:
        return
    written = float(order.dose_quantity) * per_unit
    drug = str(getattr(order, "drug_id", "") or key)
    interval = neonatal_interval_hours(drug, age_days)
    if interval is not None:
        order.frequency = f"q{interval}h"
        order.display_name = name = _INTERVAL.sub(order.frequency, name, count=1)
    mg = _child_mg(drug, written, age_months, weight_kg, country, age_days)
    if mg is None or mg >= written:
        return
    order.dose_quantity = mg
    order.dose_unit = "mg"
    m = _MG_OR_G.search(name)
    if m and not (m.end() < len(name) and name[m.end()] == "/"):
        order.display_name = name[: m.start()] + f"{mg:g}mg" + name[m.end() :]
