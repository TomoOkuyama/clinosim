"""Renal dose adjustment of inpatient antibiotics (Issue #3638).

A listed antibiotic (``reference_data/renal_antibiotic_dosing.yaml``: meropenem
and, in the US, piperacillin / tazobactam, the drugs whose labels were read) is
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

from pydantic import BaseModel, ConfigDict, Field

from clinosim.codes.drugs import drug_ref
from clinosim.countries import country_code
from clinosim.datafiles import load_validated_yaml
from clinosim.locale.i18n import t
from clinosim.types.encounter import Order, OrderResult

_REF = Path(__file__).resolve().parent / "reference_data" / "renal_antibiotic_dosing.yaml"
_STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|g)\b", re.IGNORECASE)
_INTERVAL = re.compile(r"\bq\d+h\b", re.IGNORECASE)
_MG_PER_UNIT = {"mg": 1.0, "g": 1000.0}
_MG_PER_G = _MG_PER_UNIT["g"]
_SAME_DOSE_TOLERANCE_MG = 1e-6
_HOURS_PER_DAY = 24
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
    dose_factor: float = Field(gt=0, le=1)
    interval_hours: int = Field(gt=0, le=24)


class _CountryRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference_dose_mg: float | None = Field(default=None, gt=0)
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


def _rewritten_name(name: str, mg: float, interval: str) -> str:
    """``name`` with a written strength and interval following the new regimen."""
    new = f"{mg / _MG_PER_G:g}g" if mg >= _MG_PER_G else f"{mg:g}mg"
    name = _STRENGTH.sub(new, name, count=1)
    return _INTERVAL.sub(interval.lower(), name, count=1) if interval.upper().startswith("Q") else name


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


def apply_renal_dose(
    order: Order, patient: Any, admission_time: datetime, at: datetime, context: RenalDoseContext
) -> None:
    """Decide the renal dose of an antibiotic ``order`` at its first dose
    (``at``), in place; a no-op for an order already decided, an unlisted drug
    or country, or a patient without a clearance. Idempotent. The age is the
    age at admission and the weight the one charted on the encounter."""
    if order.renal_crcl_ml_min is not None or order.dose_quantity is None:
        return
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
    per_unit = _MG_PER_UNIT.get(str(order.dose_unit).lower())
    if band is None or per_unit is None:
        return
    written_mg = float(order.dose_quantity) * per_unit
    if rule.reference_dose_mg is not None and abs(written_mg - rule.reference_dose_mg) > _SAME_DOSE_TOLERANCE_MG:
        return
    mg = written_mg * band.dose_factor
    frequency = "DAILY" if band.interval_hours == _HOURS_PER_DAY else f"Q{band.interval_hours}H"
    if abs(mg - written_mg) < _SAME_DOSE_TOLERANCE_MG and (order.frequency or "").upper() == frequency:
        return
    order.dose_unit = "mg" if mg < _MG_PER_G else "g"
    order.dose_quantity = round(mg if mg < _MG_PER_G else mg / _MG_PER_G, 3)
    order.frequency = frequency
    order.frequency_per_day = _HOURS_PER_DAY // band.interval_hours
    order.display_name = _rewritten_name(order.display_name or "", mg, frequency)
    order.renal_dose_adjusted = True
    order.clinical_intent = (order.clinical_intent or "") + t(
        "order_intent.dose_adjusted_crcl", "en", crcl=f"{crcl:.0f}"
    )
    order.clinical_intent_ja = (order.clinical_intent_ja or "") + t(
        "order_intent.dose_adjusted_crcl", "ja", crcl=f"{crcl:.0f}"
    )
