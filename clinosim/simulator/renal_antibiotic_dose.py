"""Renal dose adjustment of inpatient antibiotics (Issue #3638).

A listed antibiotic (``reference_data/renal_antibiotic_dosing.yaml``: the drugs
and countries whose label was read and states creatinine-clearance bands) is
given at a dose and interval chosen from the patient's creatinine clearance
(Cockcroft-Gault). The decision is made once per order, at its first dose, from
the latest creatinine resulted by the order time, else the stay's first result
(the admission panel); the order's dose, frequency and intent note are then
rewritten in place, so the order, the administrations and the MedicationRequest
state the same regimen. A creatinine that changes later does not re-dose the
order (a limitation: the regimen is reviewed once). RNG-free.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.codes.drugs import drug_ref
from clinosim.countries import country_code
from clinosim.datafiles import load_validated_yaml
from clinosim.locale.i18n import t
from clinosim.types.encounter import Order, OrderResult

_REF = Path(__file__).resolve().parent / "reference_data" / "renal_antibiotic_dosing.yaml"
_STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|g)\b", re.IGNORECASE)
_PER_KG_STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*mg\s*/\s*kg\b", re.IGNORECASE)
_INTERVAL = re.compile(r"\bq\d+(?:-\d+)?h\b|\bdaily\b", re.IGNORECASE)
_MG_PER_UNIT = {"mg": 1.0, "g": 1000.0}
_MG_PER_G = _MG_PER_UNIT["g"]
_SAME_DOSE_TOLERANCE_MG = 1e-6
_HOURS_PER_DAY = 24
# A band's interval: a whole fraction of a day or a whole number of days (q48h).
_MAX_INTERVAL_HOURS = 48
_DAYS_PER_YEAR = 365.25


class _CockcroftGault(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    age_base: int = Field(gt=0)
    denominator: float = Field(gt=0)
    female_factor: float = Field(gt=0, le=1)
    min_age_years: int = Field(gt=0)


class _Band(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_crcl: int = Field(gt=0)
    dose_factor: float | None = Field(default=None, gt=0, le=1)
    daily_dose_mg: float | None = Field(default=None, gt=0)
    dose_mg: float | None = Field(default=None, gt=0)
    interval_hours: int = Field(gt=0, le=_MAX_INTERVAL_HOURS)

    @model_validator(mode="after")
    def _one_dose_rule(self) -> _Band:
        if sum(v is not None for v in (self.dose_factor, self.daily_dose_mg, self.dose_mg)) != 1:
            raise ValueError("a band gives exactly one of dose_factor, daily_dose_mg and dose_mg")
        if _HOURS_PER_DAY % self.interval_hours and self.interval_hours % _HOURS_PER_DAY:
            raise ValueError("interval_hours divides a day or is a whole number of days")
        return self


class _CountryRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference_dose_mg: float | None = Field(default=None, gt=0)
    first_dose_unchanged: bool = False
    bands: list[_Band] = Field(min_length=1)


class RenalAntibioticDosing(BaseModel):
    """Schema of ``reference_data/renal_antibiotic_dosing.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    cockcroft_gault: _CockcroftGault
    drugs: dict[str, dict[str, _CountryRule]] = Field(min_length=1)


class RenalDoseContext(NamedTuple):
    """What the MAR needs to decide an order's renal dose: the stay's results
    (creatinine among them) and the country."""

    results: Sequence[OrderResult]
    country: str


@functools.cache
def _rules() -> RenalAntibioticDosing:
    return RenalAntibioticDosing.model_validate(load_validated_yaml(_REF, RenalAntibioticDosing))


def cockcroft_gault_ml_min(age_years: float, weight_kg: float, creatinine_mg_dl: float, sex: str) -> float | None:
    """Cockcroft-Gault creatinine clearance (mL/min); ``None`` when the inputs
    cannot give one (no weight or creatinine, an age at or above the base)."""
    cg = _rules().cockcroft_gault
    if weight_kg <= 0 or creatinine_mg_dl <= 0 or age_years >= cg.age_base:
        return None
    crcl = (cg.age_base - age_years) * weight_kg / (cg.denominator * creatinine_mg_dl)
    return crcl * cg.female_factor if str(sex).upper().startswith("F") else crcl


def _creatinine_at(results: Sequence[OrderResult], at: datetime, lab: str) -> float | None:
    """The latest creatinine resulted at or before ``at``, else the stay's first."""
    series = sorted(
        (r.result_datetime, float(r.value))
        for r in results
        if r.lab_name == lab and isinstance(r.value, (int, float)) and r.result_datetime is not None
    )
    if not series:
        return None
    before = [v for when, v in series if when <= at]
    return before[-1] if before else series[0][1]


def _rewritten_name(name: str, mg: float, interval: str, *, in_mg: bool = False) -> str:
    """``name`` with a written strength and interval following the new regimen."""
    new = f"{mg / _MG_PER_G:g}g" if mg >= _MG_PER_G and not in_mg else f"{mg:g}mg"
    name = (
        _PER_KG_STRENGTH.sub(new, name, count=1) if _PER_KG_STRENGTH.search(name) else _STRENGTH.sub(new, name, count=1)
    )
    # A once-daily regimen drops the written "q12h" for "daily" (Issue #3917).
    return _INTERVAL.sub("daily" if interval.upper() == "DAILY" else interval.lower(), name, count=1)


def creatinine_clearance(
    patient: Any, encounter_id: str, admission_time: datetime, at: datetime, context: RenalDoseContext
) -> float | None:
    """The Cockcroft-Gault creatinine clearance (mL/min) of a patient at ``at``:
    the latest creatinine resulted by then, else the stay's first; the age at
    admission and the weight charted on the encounter. ``None`` for a minor
    (under ``min_age_years``) or when no creatinine or weight gives one. Shared
    by the renal dosing of antibiotics and of the anticoagulants a complication
    starts (Issue #3864)."""
    from clinosim.modules.population.encounter_anthropometry import encounter_weight_kg
    from clinosim.simulator.aki_response import aki_response_rules

    rules = _rules()
    dob = getattr(patient, "date_of_birth", None)
    age_years = (
        (admission_time.date() - dob).days / _DAYS_PER_YEAR if dob is not None else float(getattr(patient, "age", 0))
    )
    if age_years < rules.cockcroft_gault.min_age_years:
        return None
    creatinine = _creatinine_at(context.results, at, aki_response_rules().creatinine_lab)
    if creatinine is None:
        return None
    weight = encounter_weight_kg(patient, encounter_id, admission_time, context.country)
    return cockcroft_gault_ml_min(age_years, weight, creatinine, str(patient.sex))


def _written_mg(order: Order, patient: Any, admission_time: datetime, context: RenalDoseContext) -> float | None:
    """The mg of one written dose; a per-kg dose is for the weight charted on
    the encounter, capped at the written maximum. ``None`` for any other unit."""
    from clinosim.modules.population.encounter_anthropometry import encounter_weight_kg

    unit = str(order.dose_unit).lower()
    quantity = float(order.dose_quantity or 0.0)
    if unit in _MG_PER_UNIT:
        return quantity * _MG_PER_UNIT[unit]
    if unit == "mg/kg":
        mg = quantity * encounter_weight_kg(patient, order.encounter_id, admission_time, context.country)
        return min(mg, float(order.dose_max_quantity)) if order.dose_max_quantity else mg
    return None


def _written_interval_hours(order: Order) -> float | None:
    """Hours between the written doses; ``None`` when the order states no
    per-day count."""
    per_day = order.frequency_per_day
    return _HOURS_PER_DAY / per_day if per_day else None


def _frequency(interval_hours: int) -> tuple[str, int | None]:
    """The frequency label and per-day count of a band's interval; a cadence
    longer than a day ("Q48H") has no per-day count, like a weekly order."""
    if interval_hours == _HOURS_PER_DAY:
        return "DAILY", 1
    if interval_hours > _HOURS_PER_DAY:
        return f"Q{interval_hours}H", None
    return f"Q{interval_hours}H", _HOURS_PER_DAY // interval_hours


def keeps_first_dose(order: Order, country: str) -> bool:
    """Whether the label of ``order``'s drug fixes the first dose apart from
    the renal maintenance regimen (``first_dose_unchanged``)."""
    rule = _rules().drugs.get(order.drug_id or drug_ref(order.display_name or ""), {}).get(country_code(country))
    return bool(rule and rule.first_dose_unchanged)


def apply_renal_dose(
    order: Order, patient: Any, admission_time: datetime, at: datetime, context: RenalDoseContext
) -> None:
    """Decide the renal dose of an antibiotic ``order`` at its first dose
    (``at``), in place; a no-op for an order already decided, an unlisted drug
    or country, or a patient without a clearance. Idempotent. The age is the
    age at admission and the weight the one charted on the encounter."""
    if order.renal_crcl_ml_min is not None or order.dose_quantity is None or order.single_dose:
        return  # a one-time dose has no interval to adjust (the labels' tables follow the initial dose)
    if str(order.route or "").upper() == "PO":
        return  # the labels' tables are for the injections (oral vancomycin is not absorbed)
    rules = _rules()
    key = order.drug_id or drug_ref(order.display_name or "")
    rule = rules.drugs.get(key, {}).get(country_code(context.country))
    if rule is None:
        return
    crcl = creatinine_clearance(patient, order.encounter_id, admission_time, at, context)
    if crcl is None:
        return
    order.renal_crcl_ml_min = round(crcl, 1)
    band = next((b for b in sorted(rule.bands, key=lambda b: b.max_crcl) if round(crcl) <= b.max_crcl), None)
    if band is None:
        return
    written_interval = _written_interval_hours(order)
    if written_interval is not None and band.interval_hours < written_interval:
        return  # an order given less often than the band is not made more frequent
    if band.daily_dose_mg is not None:
        # An absolute daily dose (vancomycin): the written dose may be weight
        # based, and a regimen already at or below the label dose is kept.
        written_mg = _written_mg(order, patient, admission_time, context)
        if written_mg is None or written_mg * (order.frequency_per_day or 1) <= band.daily_dose_mg:
            return
        mg = band.daily_dose_mg * band.interval_hours / _HOURS_PER_DAY
    else:
        per_unit = _MG_PER_UNIT.get(str(order.dose_unit).lower())
        if per_unit is None:
            return
        written_mg = float(order.dose_quantity) * per_unit
        if rule.reference_dose_mg is not None and abs(written_mg - rule.reference_dose_mg) > _SAME_DOSE_TOLERANCE_MG:
            return
        # A label table stated in mg per dose (``dose_mg``) or as a fraction of the written dose.
        mg = band.dose_mg if band.dose_mg is not None else written_mg * (band.dose_factor or 1.0)
    frequency, per_day = _frequency(band.interval_hours)
    if abs(mg - written_mg) < _SAME_DOSE_TOLERANCE_MG and (order.frequency or "").upper() == frequency:
        return
    in_mg = mg < _MG_PER_G or band.daily_dose_mg is not None  # a label table stated in mg stays in mg
    order.dose_unit = "mg" if in_mg else "g"
    order.dose_quantity = round(mg if in_mg else mg / _MG_PER_G, 3)
    order.dose_max_quantity = None  # a per-kg order's cap does not apply to the absolute dose
    order.frequency = frequency
    order.frequency_per_day = per_day
    order.display_name = _rewritten_name(order.display_name or "", mg, frequency, in_mg=in_mg)
    order.renal_dose_adjusted = True
    order.clinical_intent = (order.clinical_intent or "") + t(
        "order_intent.dose_adjusted_crcl", "en", crcl=f"{crcl:.0f}"
    )
    order.clinical_intent_ja = (order.clinical_intent_ja or "") + t(
        "order_intent.dose_adjusted_crcl", "ja", crcl=f"{crcl:.0f}"
    )
