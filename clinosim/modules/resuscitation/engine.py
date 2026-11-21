"""Resuscitation engine — YAML loader + the CPR record and epinephrine doses.

Determinism: the duration comes from a sub-RNG seeded by the patient and
encounter ids (``seeding.resuscitation_seed``); no existing stream is read.
Everything else is a pure function of the death time and the YAML.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim import determinism
from clinosim.codes import snomed_concepts as sc
from clinosim.codes.procedures import country_procedure_code
from clinosim.datafiles import load_data_yaml
from clinosim.locale.localized import language_slot, localized_field
from clinosim.seeding import resuscitation_seed
from clinosim.types.encounter import MedicationAdministration, Order, OrderStatus, OrderType
from clinosim.types.procedure import ProcedureRecord

_YAML_PATH = Path(__file__).resolve().parent / "reference_data" / "resuscitation_rules.yaml"

# Suffix of the id of the epinephrine order of an attempt: its doses a few
# minutes apart are separate administrations, which the FHIR emit's same-hour
# duplicate guard must not collapse (see ``is_resuscitation_order``).
_EPINEPHRINE_ORDER_SUFFIX = "-CPR-EPI"


class _Range(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: int = Field(ge=1)
    max: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> _Range:
        if self.max < self.min:
            raise ValueError("duration_minutes: max below min")
        return self


class _Procedure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    location: str = ""

    @model_validator(mode="after")
    def _in_catalog(self) -> _Procedure:
        from clinosim.codes.procedures import catalog_procedure_types

        if self.type not in catalog_procedure_types():
            raise ValueError(f"resuscitation_rules.yaml: procedure type {self.type!r} is not in the procedure catalog")
        return self


class _Epinephrine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drug: str = Field(min_length=1)
    dose_quantity: float = Field(gt=0)
    dose_unit: str = Field(min_length=1)
    route: str = Field(min_length=1)
    frequency: str = ""
    min_age: int = Field(ge=0)
    interval_minutes: int = Field(ge=1)
    first_dose_offset_minutes: int = Field(ge=0)
    clinical_intent: dict[str, str]

    @model_validator(mode="after")
    def _known_drug(self) -> _Epinephrine:
        from clinosim.codes.drugs import drug_ref

        if not drug_ref(self.drug):
            raise ValueError(f"resuscitation_rules.yaml: drug {self.drug!r} is not in the drug catalog")
        return self


class ResuscitationRules(BaseModel):
    """Shape of resuscitation_rules.yaml."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    attempt_tier: str = Field(min_length=1)
    encounter_types: list[str] = Field(min_length=1)
    procedure: _Procedure
    duration_minutes: _Range
    epinephrine: _Epinephrine

    @model_validator(mode="after")
    def _known_tier(self) -> ResuscitationRules:
        from clinosim.modules.code_status.engine import load_reference

        if self.attempt_tier not in {t["key"] for t in load_reference()["tiers"]}:
            raise ValueError(f"resuscitation_rules.yaml: attempt_tier {self.attempt_tier!r} is not a code-status tier")
        return self


@lru_cache(maxsize=1)
def load_rules() -> ResuscitationRules:
    return ResuscitationRules.model_validate(load_data_yaml(_YAML_PATH) or {})


@lru_cache(maxsize=1)
def attempt_status_code() -> str:
    """SNOMED code of the code-status tier an attempt is made for."""
    from clinosim.modules.code_status.engine import load_reference

    tier = load_rules().attempt_tier
    return next(str(t["snomed"]) for t in load_reference()["tiers"] if t["key"] == tier)


def is_resuscitation_order(order_id: str) -> bool:
    """Whether ``order_id`` is the epinephrine order of a resuscitation attempt."""
    return str(order_id or "").endswith(_EPINEPHRINE_ORDER_SUFFIX)


def attempt_minutes(patient_id: str, encounter_id: str, admission: datetime, death: datetime) -> int:
    """Duration of the attempt: drawn from the per-stay sub-RNG between the
    YAML bounds, never longer than the stay itself."""
    bounds = load_rules().duration_minutes
    rng = determinism.default_rng(resuscitation_seed(patient_id, encounter_id))
    minutes = int(rng.integers(bounds.min, bounds.max + 1))
    stay = int((death - admission).total_seconds() // 60)
    return max(1, min(minutes, stay))


def build_cpr_procedure(
    patient_id: str, encounter_id: str, death: datetime, minutes: int, country: str, performer_id: str
) -> ProcedureRecord:
    """The CPR procedure record ending at ``death``."""
    from clinosim.codes.procedures import procedure_code

    rules = load_rules().procedure
    cpt, kcode = procedure_code(rules.type, "US"), procedure_code(rules.type, "JP")
    return ProcedureRecord(
        procedure_id=f"PROC-{patient_id}-CPR",
        patient_id=patient_id,
        encounter_id=encounter_id,
        procedure_type=rules.type,
        procedure_code=country_procedure_code(country, {"k-codes": kcode, "cpt": cpt}),
        procedure_code_jp=kcode,
        procedure_code_us=cpt,
        start_datetime=death - timedelta(minutes=minutes),
        end_datetime=death,
        duration_minutes=minutes,
        primary_surgeon_id=performer_id,
        anesthesia_type="none",
        category_code=sc.PROCEDURE_CATEGORY_THERAPEUTIC,
        outcome_code=sc.PROCEDURE_UNSUCCESSFUL,
        location_id=rules.location,
    )


def build_epinephrine(
    patient_id: str, encounter_id: str, start: datetime, death: datetime, *, orderer_id: str, nurse_id: str
) -> tuple[Order, list[MedicationAdministration]]:
    """The epinephrine order of the attempt and one administration per
    interval from the first dose until the death."""
    rule = load_rules().epinephrine
    order = Order(
        order_id=f"ORD-{encounter_id}{_EPINEPHRINE_ORDER_SUFFIX}",
        encounter_id=encounter_id,
        patient_id=patient_id,
        order_type=OrderType.MEDICATION,
        display_name=rule.drug,
        urgency="stat",
        clinical_intent=localized_field(rule.model_dump(), "clinical_intent", "en"),
        clinical_intent_ja=language_slot(rule.clinical_intent, "ja"),
        ordered_datetime=start,
        ordered_by=orderer_id,
        status=OrderStatus.PLACED,
        dose_quantity=rule.dose_quantity,
        dose_unit=rule.dose_unit,
        frequency=rule.frequency,
        route=rule.route,
    )
    dose = f"{rule.dose_quantity:g} {rule.dose_unit}"
    times: list[datetime] = []
    t = start + timedelta(minutes=rule.first_dose_offset_minutes)
    while t < death:
        times.append(t)
        t += timedelta(minutes=rule.interval_minutes)
    mars = [
        MedicationAdministration(
            order_id=order.order_id,
            drug_name=rule.drug,
            scheduled_datetime=t,
            actual_datetime=t,
            status="given",
            dose=dose,
            route=rule.route,
            administered_by=nurse_id,
        )
        for t in times
    ]
    if times:
        order.end_datetime = times[-1]
    return order, mars
