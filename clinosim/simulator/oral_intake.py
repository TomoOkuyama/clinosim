"""Oral intake of a patient who cannot swallow safely (Issue #3552).

A patient whose latest recorded AVPU level is P or U is nil by mouth, and so
is a ventilated one or one on non-invasive ventilation (``reference_data/oral_intake.yaml``): the diet order is
NPO and every oral-route dose scheduled in that state is held with a reason.
Everything here is RNG-free.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clinosim.datafiles import load_data_yaml
from clinosim.types.encounter import MedicationAdministration, VitalSignRecord

__all__ = ["OralIntakeRules", "apply_oral_intake_holds", "first_npo_readings", "npo_reason_at", "oral_intake_rules"]

_AVPU = frozenset("AVPU")


class OralIntakeRules(BaseModel):
    """Schema of ``reference_data/oral_intake.yaml`` (Issue #3552)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    npo_consciousness_levels: tuple[str, ...] = Field(min_length=1)
    npo_while_ventilated: bool
    npo_while_niv: bool
    npo_diet: str = Field(min_length=1)
    oral_route: str = Field(min_length=1)
    hold_reason_consciousness: str = Field(min_length=1)
    hold_reason_ventilated: str = Field(min_length=1)
    hold_reason_niv: str = Field(min_length=1)

    @field_validator("npo_consciousness_levels")
    @classmethod
    def _avpu_levels(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not set(v) <= _AVPU:
            raise ValueError(f"npo_consciousness_levels {v} must be AVPU letters")
        return v

    @model_validator(mode="after")
    def _localized_reasons(self) -> OralIntakeRules:
        from clinosim.locale.loader import load_medication_hold_reasons

        known = load_medication_hold_reasons()
        for reason in (self.hold_reason_consciousness, self.hold_reason_ventilated, self.hold_reason_niv):
            if reason not in known:
                raise ValueError(f"reason {reason!r} is not in medication_hold_reasons.yaml")
        return self


@functools.cache
def oral_intake_rules() -> OralIntakeRules:
    """The validated oral-intake rules."""
    return OralIntakeRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "oral_intake.yaml")
    )


def _latest_level_at(vitals: Iterable[VitalSignRecord], at: datetime) -> str | None:
    """AVPU level of the latest reading at or before ``at`` (None: no reading)."""
    best: VitalSignRecord | None = None
    for v in vitals:
        if v.timestamp <= at and (best is None or v.timestamp >= best.timestamp):
            best = v
    return best.consciousness_level if best is not None else None


def npo_reason_at(
    vitals: Iterable[VitalSignRecord],
    at: datetime,
    ventilated_at: Callable[[datetime], bool],
    *,
    niv_at: Callable[[datetime], bool] | None = None,
) -> str | None:
    """The reason the patient is nil by mouth at ``at`` (the latest AVPU
    reading is P / U, or on the ventilator or non-invasive ventilation, Issue
    #3705), else None."""
    rules = oral_intake_rules()
    if rules.npo_while_ventilated and ventilated_at(at):
        return rules.hold_reason_ventilated
    if rules.npo_while_niv and niv_at is not None and niv_at(at):
        return rules.hold_reason_niv
    if _latest_level_at(vitals, at) in rules.npo_consciousness_levels:
        return rules.hold_reason_consciousness
    return None


def first_npo_readings(vitals: Iterable[VitalSignRecord], since: datetime) -> list[datetime]:
    """Times of the readings at or after ``since`` whose AVPU level makes the
    patient nil by mouth."""
    levels = oral_intake_rules().npo_consciousness_levels
    return [v.timestamp for v in vitals if v.timestamp >= since and v.consciousness_level in levels]


def apply_oral_intake_holds(
    mars: Iterable[MedicationAdministration],
    vitals: Iterable[VitalSignRecord],
    ventilated_at: Callable[[datetime], bool],
    *,
    niv_at: Callable[[datetime], bool] | None = None,
) -> int:
    """Hold, in place, each given oral dose of ``mars`` scheduled while the
    patient is nil by mouth (``npo_reason_at``, judged at the dose time).
    Returns the number held. Draws nothing."""
    rules = oral_intake_rules()
    records = list(vitals)
    held = 0
    for mar in mars:
        if mar.status != "given" or mar.route != rules.oral_route:
            continue
        reason = npo_reason_at(records, mar.actual_datetime or mar.scheduled_datetime, ventilated_at, niv_at=niv_at)
        if reason:
            mar.status, mar.hold_reason, mar.actual_datetime = "held", reason, None
            held += 1
    return held
