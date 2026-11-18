"""Acute kidney injury during the stay: held drugs and the discharge gate
(Issue #3281).

From the stay's serum creatinine results the KDIGO 2012 AKI definition is
applied (``aki_course``). While the latest creatinine meets it, scheduled doses
of nephrotoxic or renally cleared drugs (NSAIDs, ACE inhibitors / ARBs,
thiazide and potassium-sparing diuretics, metformin) are held
(``AkiCourse.holds``), and the discharge gate keeps the patient in hospital
while the creatinine has not fallen or a fever persists
(``discharge_findings_unresolved``). Values live in
``reference_data/aki_response.yaml``. Everything here is RNG-free.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim.codes.drugs import all_drug_ids, drug_classes, drug_key
from clinosim.datafiles import load_data_yaml
from clinosim.types.encounter import OrderResult, VitalSignRecord


class AkiResponseRules(BaseModel):
    """Schema of ``reference_data/aki_response.yaml`` (Issue #3281)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    creatinine_lab: str = Field(min_length=1)
    abs_rise_mg_dl: float = Field(gt=0)
    abs_rise_window_hours: int = Field(gt=0)
    ratio: float = Field(gt=1)
    recovery_fall_fraction: float = Field(gt=0, lt=1)
    hold_classes: tuple[str, ...] = ()
    hold_drugs: tuple[str, ...] = ()
    reason: str = Field(min_length=1)
    fever_celsius: float = Field(gt=0)
    fever_window_hours: int = Field(gt=0)
    max_extension_days: int = Field(ge=0)

    @field_validator("hold_classes")
    @classmethod
    def _catalog_classes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        known = {c for d in all_drug_ids() for c in drug_classes(d)}
        unknown = sorted(set(v) - known)
        if unknown:
            raise ValueError(f"drug classes {unknown} are not classes of any catalog drug")
        return v

    @field_validator("hold_drugs")
    @classmethod
    def _catalog_drugs(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(d for d in v if d not in set(all_drug_ids()))
        if unknown:
            raise ValueError(f"hold_drugs {unknown} are not catalog drug ids")
        return v

    @field_validator("reason")
    @classmethod
    def _localized_reason(cls, v: str) -> str:
        from clinosim.locale.loader import load_medication_hold_reasons

        if v not in load_medication_hold_reasons():
            raise ValueError(f"reason {v!r} is not in medication_hold_reasons.yaml")
        return v


@functools.cache
def aki_response_rules() -> AkiResponseRules:
    """The validated AKI hold and discharge-gate rules."""
    return AkiResponseRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "aki_response.yaml")
    )


def holds_for_aki(drug: str) -> bool:
    """True when the drug (catalog id, name or order string) is held during AKI."""
    rules = aki_response_rules()
    if set(drug_classes(drug)) & set(rules.hold_classes):
        return True
    return drug_key(drug) in rules.hold_drugs


@dataclass(frozen=True)
class AkiCourse:
    """The stay's creatinine results ``(resulted at, mg/dL, meets the AKI
    definition)`` in time order."""

    points: tuple[tuple[datetime, float, bool], ...] = ()

    def active_at(self, at: datetime) -> bool:
        """True when the latest creatinine resulted at or before ``at`` meets
        the AKI definition."""
        active = False
        for when, _value, meets in self.points:
            if when > at:
                break
            active = meets
        return active

    @property
    def active(self) -> bool:
        """True when the latest creatinine meets the AKI definition."""
        return bool(self.points) and self.points[-1][2]

    @property
    def not_improving(self) -> bool:
        """True while AKI is active and the latest creatinine has not fallen by
        ``recovery_fall_fraction`` from its peak since the injury began."""
        if not self.active:
            return False
        first = next(i for i, p in enumerate(self.points) if p[2])
        peak = max(p[1] for p in self.points[first:])
        return self.points[-1][1] > (1 - aki_response_rules().recovery_fall_fraction) * peak


def aki_course(results: Iterable[OrderResult]) -> AkiCourse:
    """Apply the KDIGO 2012 definition (Recommendation 2.1.1) to every
    creatinine result: a rise of ``abs_rise_mg_dl`` over the lowest result of
    the preceding ``abs_rise_window_hours``, or ``ratio`` times the lowest
    result of the stay so far."""
    rules = aki_response_rules()
    series = sorted(
        (r.result_datetime, float(r.value))
        for r in results
        if r.lab_name == rules.creatinine_lab and isinstance(r.value, (int, float))
    )
    abs_window = timedelta(hours=rules.abs_rise_window_hours)
    points: list[tuple[datetime, float, bool]] = []
    for i, (when, value) in enumerate(series):
        earlier = series[:i]
        low_abs = min((v for t, v in earlier if when - t <= abs_window), default=None)
        low_ratio = min((v for _t, v in earlier), default=None)
        meets = (low_abs is not None and value - low_abs >= rules.abs_rise_mg_dl - 1e-9) or (
            low_ratio is not None and value >= rules.ratio * low_ratio - 1e-9
        )
        points.append((when, value, meets))
    return AkiCourse(tuple(points))


def fever_persists(vitals: Iterable[VitalSignRecord]) -> bool:
    """True when a temperature of at least ``fever_celsius`` was recorded in
    the ``fever_window_hours`` up to the latest recorded vital signs."""
    rules = aki_response_rules()
    temps = [(v.timestamp, v.temperature_celsius) for v in vitals if v.temperature_celsius is not None]
    if not temps:
        return False
    since = max(t for t, _ in temps) - timedelta(hours=rules.fever_window_hours)
    return any(t > since and c >= rules.fever_celsius for t, c in temps)


def discharge_findings_unresolved(course: AkiCourse, vitals: Iterable[VitalSignRecord]) -> bool:
    """True while the patient is not fit to go home for the kidneys or a
    fever: AKI that has not begun to recover, or a fever in the last day."""
    return course.not_improving or fever_persists(vitals)
