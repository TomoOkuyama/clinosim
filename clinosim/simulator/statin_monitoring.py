"""Lipid monitoring and statin titration at chronic follow-up visits (Issue #2877).

A patient with dyslipidemia on a statin has a full lipid panel (TC, LDL, HDL,
TG) at the follow-up visit that renews their prescriptions: at their first
monitoring visit, 4 weeks or more after a statin change, and otherwise every
``maintenance_min_days``. When the last panel's LDL is at or above the
patient's step-up threshold, the next monitoring visit moves the statin one
step up the country's ladder (moderate -> high intensity in the US, within the
usual maximum dose in Japan) and renews it at the new dose; the renewal
replaces the previous prescription of the same drug at FHIR export
(``modules/order/prescription_supersede.py``). Thresholds, ladders and
cadence: ``reference_data/statin_monitoring.yaml``.

The state lives on the person's ``OutpatientVisitLedger`` (shared by the
per-year profiles), and ``restore_titrated_statin`` carries a titrated dose
into the next year's profile. Draws no randomness.

The LDL a panel reports falls with the intensity of the statin taken
(``physiology/statin_response.py``, Issue #2917), so a titration lowers the
LDL of the later panels.
"""

from __future__ import annotations

import dataclasses
import functools
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.codes.drugs import drug_classes, drug_ref, find_drug
from clinosim.codes.valuesets import concept_group, has_condition
from clinosim.datafiles import load_data_yaml
from clinosim.types.patient import HomeMedication

_YAML = Path(__file__).resolve().parent / "reference_data" / "statin_monitoring.yaml"
_STATIN_CLASS = "statin"
_DOSE_MG = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*mg\b", re.IGNORECASE)


class _StepUpRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value_set: str | None = None
    ldl_mg_dl: float = Field(gt=0)


class _CountryRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_up_ldl: list[_StepUpRule]
    steps: dict[str, dict[float, float]]

    @model_validator(mode="after")
    def _check(self) -> _CountryRules:
        if not self.step_up_ldl or self.step_up_ldl[-1].value_set is not None:
            raise ValueError("step_up_ldl must end with a rule without a value_set")
        for rule in self.step_up_ldl:
            if rule.value_set is not None:
                concept_group(rule.value_set)  # KeyError on an unknown group
        for drug_id, ladder in self.steps.items():
            if find_drug(drug_id) is None or _STATIN_CLASS not in drug_classes(drug_id):
                raise ValueError(f"steps: {drug_id!r} is not a catalog statin")
            if any(nxt <= cur for cur, nxt in ladder.items()):
                raise ValueError(f"steps: {drug_id!r} must step up")
        return self


class StatinMonitoringRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lipid_panel: list[str] = Field(min_length=1)
    recheck_min_days_after_change: int = Field(gt=0)
    maintenance_min_days: int = Field(gt=0)
    countries: dict[str, _CountryRules]


@functools.cache
def statin_monitoring_rules() -> StatinMonitoringRules:
    """The validated ``statin_monitoring.yaml`` (shared, read-only)."""
    return StatinMonitoringRules.model_validate(load_data_yaml(_YAML))


@dataclasses.dataclass(frozen=True)
class StatinTitration:
    """A step up the statin ladder made at a visit."""

    drug_name: str
    from_dose: str
    to_dose: str
    ldl: float
    panel_on: date


def _dose_mg(dose: str) -> float | None:
    match = _DOSE_MG.match(dose or "")
    return float(match.group(1)) if match else None


def _format_mg(mg: float) -> str:
    return f"{mg:g}mg"


def _statin_id(med: Any) -> str:
    return str(getattr(med, "drug_id", "") or "") or drug_ref(str(getattr(med, "drug_name", "") or ""))


def current_statin(patient: Any) -> HomeMedication | None:
    """The patient's statin among their home medications, if any."""
    for med in getattr(patient, "current_medications", None) or []:
        if _STATIN_CLASS in drug_classes(_statin_id(med)):
            return med
    return None


def _signature(med: HomeMedication | None) -> str:
    return f"{_statin_id(med)} {med.dose}" if med is not None else ""


def _day(when: datetime | date) -> date:
    return when.date() if isinstance(when, datetime) else when


def is_statin_monitoring_visit(patient: Any, visit_type: str, spec: dict) -> bool:
    """A chronic follow-up visit that renews the prescriptions of a patient
    with dyslipidemia on a statin."""
    return (
        visit_type == "chronic_followup"
        and bool(spec.get("prescriptions_renewed"))
        and has_condition(patient, "dyslipidemia")
        and current_statin(patient) is not None
    )


def step_up_ldl(patient: Any, country: str) -> float | None:
    """LDL (mg/dL) at or above which the patient's statin is stepped up;
    ``None`` for a country without rules."""
    rules = statin_monitoring_rules().countries.get(country.upper())
    if rules is None:
        return None
    for rule in rules.step_up_ldl:
        if rule.value_set is None or has_condition(patient, rule.value_set):
            return rule.ldl_mg_dl
    return None  # pragma: no cover — the model requires a closing rule


def _replace_statin(patient: Any, old: HomeMedication, new: HomeMedication) -> None:
    patient.current_medications = [new if med is old else med for med in patient.current_medications]


def titrate_statin(patient: Any, visit_date: datetime | date, country: str) -> StatinTitration | None:
    """Step the patient's statin up when the last panel, taken on the statin
    they still take and before today, has an LDL at or above their threshold.
    Updates ``patient.current_medications`` and the visit ledger."""
    ledger = patient.visit_ledger
    statin = current_statin(patient)
    today = _day(visit_date)
    if statin is None or ledger.lipid_panel_ldl is None or ledger.lipid_panel_on is None:
        return None
    if ledger.lipid_panel_on >= today or ledger.lipid_panel_statin != _signature(statin):
        return None
    threshold = step_up_ldl(patient, country)
    if threshold is None or ledger.lipid_panel_ldl < threshold:
        return None
    rules = statin_monitoring_rules().countries[country.upper()]
    current_mg = _dose_mg(statin.dose)
    next_mg = rules.steps.get(_statin_id(statin), {}).get(current_mg) if current_mg is not None else None
    if next_mg is None:
        return None
    new = dataclasses.replace(
        statin,
        dose=_format_mg(next_mg),
        dose_quantity=next_mg if statin.dose_quantity is not None else None,
    )
    _replace_statin(patient, statin, new)
    ledger.titrated_statin = new
    ledger.statin_changed_on = today
    return StatinTitration(
        drug_name=statin.drug_name,
        from_dose=statin.dose,
        to_dose=new.dose,
        ldl=ledger.lipid_panel_ldl,
        panel_on=ledger.lipid_panel_on,
    )


def lipid_panel_due(patient: Any, visit_date: datetime | date) -> bool:
    """Whether this monitoring visit orders the lipid panel (cadence in the
    module docstring)."""
    rules = statin_monitoring_rules()
    ledger = patient.visit_ledger
    today = _day(visit_date)
    if ledger.lipid_panel_on is None:
        return True
    current = _signature(current_statin(patient))
    if current != ledger.lipid_panel_statin:
        # Changed since the last panel: recheck 4+ weeks after a titration
        # made here; a change made elsewhere (discharge, a switch) has no
        # date on record, so it is checked now.
        if ledger.statin_changed_on is not None and current == _signature(ledger.titrated_statin):
            return (today - ledger.statin_changed_on).days >= rules.recheck_min_days_after_change
        return True
    return (today - ledger.lipid_panel_on).days >= rules.maintenance_min_days


def lipid_panel_labs(spec_labs: list[str]) -> list[str]:
    """``spec_labs`` with the lipid panel analytes it lacks appended."""
    return [*spec_labs, *(lab for lab in statin_monitoring_rules().lipid_panel if lab not in spec_labs)]


def note_lipid_panel(patient: Any, visit_date: datetime | date, lab_results: list[Any]) -> None:
    """Record the visit's LDL result (if any) on the ledger, with the statin
    the patient takes."""
    ldl = next((r.value for r in lab_results if getattr(r, "lab_name", "") == "LDL"), None)
    if not isinstance(ldl, (int, float)):
        return
    ledger = patient.visit_ledger
    ledger.lipid_panel_on = _day(visit_date)
    ledger.lipid_panel_ldl = float(ldl)
    ledger.lipid_panel_statin = _signature(current_statin(patient))


def annotate_titration(rx: Any, titration: StatinTitration | None) -> None:
    """Mark the renewed statin item of ``rx`` with the dose it replaced and
    the LDL that called for it (read by the outpatient note's plan)."""
    if rx is None or titration is None:
        return
    for item in rx.items:
        if item.get("drug_name") == titration.drug_name and item.get("dose") == titration.to_dose:
            item["titrated_from_dose"] = titration.from_dose
            item["titration_ldl"] = titration.ldl
            item["titration_panel_on"] = titration.panel_on.isoformat()


def restore_titrated_statin(patient: Any) -> None:
    """Carry the clinic's last titration into a newly activated profile: the
    same statin at a lower dose (the base regimen) is replaced by the
    titrated one. A different statin (a later switch) is left alone."""
    titrated = patient.visit_ledger.titrated_statin
    statin = current_statin(patient)
    if titrated is None or statin is None or _statin_id(statin) != _statin_id(titrated):
        return
    have, want = _dose_mg(statin.dose), _dose_mg(titrated.dose)
    if have is not None and want is not None and have < want:
        _replace_statin(patient, statin, titrated)
