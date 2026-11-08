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

Issue #2942: a monitoring visit that does not step the statin up adds the
non-statin agent (ezetimibe) when the patient is on maximal statin therapy and
the last panel's LDL, taken on that statin, is at or above the add-on
threshold (``add_lipid_add_on``); ``restore_lipid_add_on`` carries it into the
next year's profile. This replaces the longitudinal
``lipid_escalate_ezetimibe_e78`` event, which read the untreated LDL latent.
"""

from __future__ import annotations

import dataclasses
import functools
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.codes.drugs import drug_classes, drug_ref, find_drug
from clinosim.codes.valuesets import concept_group, has_condition
from clinosim.datafiles import load_data_yaml
from clinosim.modules.longitudinal.med_lookup import resolve_med_name
from clinosim.types.patient import HomeMedication

_YAML = Path(__file__).resolve().parent / "reference_data" / "statin_monitoring.yaml"
_STATIN_CLASS = "statin"
_DOSE_MG = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*mg\b", re.IGNORECASE)


LdlTargetTier = Literal["secondary_prevention", "high_risk_primary_prevention", "primary_prevention"]


class _StepUpRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value_set: str | None = None
    ldl_mg_dl: float = Field(gt=0)
    tier: LdlTargetTier | None = None


class _CountryRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_up_ldl: list[_StepUpRule]
    steps: dict[str, dict[float, float]]
    add_on_ldl: list[_StepUpRule]
    maximal_statin_mg: dict[str, float]

    @model_validator(mode="after")
    def _check(self) -> _CountryRules:
        for name, rules in (("step_up_ldl", self.step_up_ldl), ("add_on_ldl", self.add_on_ldl)):
            if not rules or rules[-1].value_set is not None:
                raise ValueError(f"{name} must end with a rule without a value_set")
            for rule in rules:
                if rule.value_set is not None:
                    concept_group(rule.value_set)  # KeyError on an unknown group
        for drug_id in [*self.steps, *self.maximal_statin_mg]:
            if find_drug(drug_id) is None or _STATIN_CLASS not in drug_classes(drug_id):
                raise ValueError(f"steps / maximal_statin_mg: {drug_id!r} is not a catalog statin")
        for drug_id, ladder in self.steps.items():
            if any(nxt <= cur for cur, nxt in ladder.items()):
                raise ValueError(f"steps: {drug_id!r} must step up")
        return self


class StatinMonitoringRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lipid_panel: list[str] = Field(min_length=1)
    add_on: str
    recheck_min_days_after_change: int = Field(gt=0)
    maintenance_min_days: int = Field(gt=0)
    countries: dict[str, _CountryRules]

    @model_validator(mode="after")
    def _check_add_on(self) -> StatinMonitoringRules:
        if find_drug(self.add_on) is None or _STATIN_CLASS in drug_classes(self.add_on):
            raise ValueError(f"add_on: {self.add_on!r} is not a catalog non-statin")
        resolve_med_name(self.add_on)  # KeyError without a chronic_medications.yaml entry
        return self


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


def _first_matching_rule(patient: Any, rules: list[_StepUpRule]) -> _StepUpRule | None:
    for rule in rules:
        if rule.value_set is None or has_condition(patient, rule.value_set):
            return rule
    return None  # pragma: no cover — the model requires a closing rule


def _first_matching_ldl(patient: Any, rules: list[_StepUpRule]) -> float | None:
    rule = _first_matching_rule(patient, rules)
    return rule.ldl_mg_dl if rule is not None else None


def ldl_target(patient: Any, country: str) -> tuple[float, LdlTargetTier] | None:
    """The LDL target (mg/dL) the patient's note states, with its risk tier:
    the step-up threshold that applies to them, when the country's rules are
    target-based (a rule with a ``tier``); ``None`` otherwise (the US)."""
    rules = statin_monitoring_rules().countries.get(country.upper())
    rule = _first_matching_rule(patient, rules.step_up_ldl) if rules is not None else None
    if rule is None or rule.tier is None:
        return None
    return rule.ldl_mg_dl, rule.tier


def step_up_ldl(patient: Any, country: str) -> float | None:
    """LDL (mg/dL) at or above which the patient's statin is stepped up;
    ``None`` for a country without rules."""
    rules = statin_monitoring_rules().countries.get(country.upper())
    return _first_matching_ldl(patient, rules.step_up_ldl) if rules is not None else None


def add_on_ldl(patient: Any, country: str) -> float | None:
    """LDL (mg/dL) at or above which a patient on maximal statin therapy
    starts the non-statin add-on; ``None`` for a country without rules."""
    rules = statin_monitoring_rules().countries.get(country.upper())
    return _first_matching_ldl(patient, rules.add_on_ldl) if rules is not None else None


def on_maximal_statin(patient: Any, country: str) -> bool:
    """Whether the patient's statin is at or above the country's maximal
    statin dose (``maximal_statin_mg``)."""
    rules = statin_monitoring_rules().countries.get(country.upper())
    statin = current_statin(patient)
    if rules is None or statin is None:
        return False
    floor = rules.maximal_statin_mg.get(_statin_id(statin))
    mg = _dose_mg(statin.dose)
    return floor is not None and mg is not None and mg >= floor


def _last_panel_on_current_statin(patient: Any, today: date) -> float | None:
    """The last panel's LDL when it was taken before today on the statin the
    patient still takes, else ``None``."""
    ledger = patient.visit_ledger
    statin = current_statin(patient)
    if statin is None or ledger.lipid_panel_ldl is None or ledger.lipid_panel_on is None:
        return None
    if ledger.lipid_panel_on >= today or ledger.lipid_panel_statin != _signature(statin):
        return None
    return float(ledger.lipid_panel_ldl)


def _replace_statin(patient: Any, old: HomeMedication, new: HomeMedication) -> None:
    patient.current_medications = [new if med is old else med for med in patient.current_medications]


def titrate_statin(patient: Any, visit_date: datetime | date, country: str) -> StatinTitration | None:
    """Step the patient's statin up when the last panel, taken on the statin
    they still take and before today, has an LDL at or above their threshold.
    Updates ``patient.current_medications`` and the visit ledger."""
    ledger = patient.visit_ledger
    statin = current_statin(patient)
    today = _day(visit_date)
    ldl = _last_panel_on_current_statin(patient, today)
    if statin is None or ldl is None or ledger.lipid_panel_on is None:
        return None
    threshold = step_up_ldl(patient, country)
    if threshold is None or ldl < threshold:
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


def _takes(patient: Any, drug_id: str) -> bool:
    return any(_statin_id(med) == drug_id for med in getattr(patient, "current_medications", None) or [])


def add_lipid_add_on(patient: Any, visit_date: datetime | date, country: str) -> HomeMedication | None:
    """Start the non-statin add-on (ezetimibe) when the patient is on
    maximal statin therapy and the last panel, taken on that statin and
    before today, has an LDL at or above their add-on threshold. Call it only
    at a visit whose statin was not stepped up. Updates
    ``patient.current_medications`` and the visit ledger."""
    from clinosim.modules import drug_safety

    rules = statin_monitoring_rules()
    today = _day(visit_date)
    ldl = _last_panel_on_current_statin(patient, today)
    if ldl is None or _takes(patient, rules.add_on) or not on_maximal_statin(patient, country):
        return None
    threshold = add_on_ldl(patient, country)
    if threshold is None or ldl < threshold:
        return None
    if drug_safety.allergy_skip_verdict(rules.add_on, list(getattr(patient, "allergies", None) or [])) is not None:
        return None
    add_on = dataclasses.replace(resolve_med_name(rules.add_on))  # a copy: the resolver is cached
    patient.current_medications = [*patient.current_medications, add_on]
    ledger = patient.visit_ledger
    ledger.lipid_add_on = add_on
    ledger.lipid_add_on_on = today
    return add_on


def restore_lipid_add_on(patient: Any) -> None:
    """Carry the add-on the clinic started into a newly activated profile."""
    add_on = patient.visit_ledger.lipid_add_on
    if add_on is not None and not _takes(patient, _statin_id(add_on)):
        patient.current_medications = [*patient.current_medications, add_on]


def lipid_panel_due(patient: Any, visit_date: datetime | date) -> bool:
    """Whether this monitoring visit orders the lipid panel (cadence in the
    module docstring)."""
    rules = statin_monitoring_rules()
    ledger = patient.visit_ledger
    today = _day(visit_date)
    if ledger.lipid_panel_on is None:
        return True
    if ledger.lipid_add_on_on is not None and ledger.lipid_add_on_on >= ledger.lipid_panel_on:
        # An add-on started since the last panel: recheck 4+ weeks after it.
        return (today - ledger.lipid_add_on_on).days >= rules.recheck_min_days_after_change
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
