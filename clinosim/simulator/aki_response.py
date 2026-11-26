"""Acute kidney injury during the stay: held drugs and the discharge gate
(Issue #3281).

From the stay's serum creatinine results the KDIGO 2012 AKI definition is
applied (``aki_course``). While the latest creatinine meets it, scheduled doses
of nephrotoxic or renally cleared drugs (NSAIDs, ACE inhibitors / ARBs,
thiazide and potassium-sparing diuretics, metformin) are held
(``AkiCourse.holds``), and the discharge gate keeps the patient in hospital
while the creatinine has not fallen, a fever persists or the potassium / total
CO2 of kidney failure persists (``discharge_findings_unresolved``); a stay that
reaches the extension cap with any of them unresolved is discharged to a skilled
nursing facility (its outcome is then unchanged or worsened, never improved,
Issue #3830) and the discharge instructions carry the recheck. Values live in
``reference_data/aki_response.yaml``. Everything here is RNG-free.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim.codes.drugs import all_drug_ids, drug_classes, drug_key
from clinosim.datafiles import load_data_yaml
from clinosim.types.encounter import OrderResult, VitalSignRecord


class LactateHoldRules(BaseModel):
    """The ``lactate_hold`` block of ``aki_response.yaml`` (Issue #3539)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lab: str = Field(min_length=1)
    hold_at_or_above_mmol_l: float = Field(gt=0)
    hold_drugs: tuple[str, ...] = Field(min_length=1)
    reason: str = Field(min_length=1)

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


class AkiResponseRules(BaseModel):
    """Schema of ``reference_data/aki_response.yaml`` (Issue #3281)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    creatinine_lab: str = Field(min_length=1)
    complication: str = Field(min_length=1)
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
    fever_max_extension_days: int = Field(ge=0)
    potassium_lab: str = Field(min_length=1)
    total_co2_lab: str = Field(min_length=1)
    unresolved_total_co2_mmol_l: float = Field(gt=0)
    lactate_hold: LactateHoldRules

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
    """The stay's creatinine results ``(resulted at, mg/dL, AKI active)`` in
    time order. The injury is sticky (Issue #3538): it is active from the first
    result that meets the definition until a result falls by
    ``recovery_fall_fraction`` from the peak since the injury began, and it is
    active again when a later result is back within that fraction of the peak."""

    points: tuple[tuple[datetime, float, bool], ...] = ()

    def active_at(self, at: datetime) -> bool:
        """True when the injury is active at the latest creatinine resulted at
        or before ``at``."""
        active = False
        for when, _value, meets in self.points:
            if when > at:
                break
            active = meets
        return active

    @property
    def active(self) -> bool:
        """True when the injury is active at the latest creatinine."""
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
    result of the stay so far. A plateau does not end the injury: after the
    first result that meets the definition, a result stays active while it is
    above ``(1 - recovery_fall_fraction)`` of the peak since then (Issue
    #3538)."""
    rules = aki_response_rules()
    series = sorted(
        (r.result_datetime, float(r.value))
        for r in results
        if r.lab_name == rules.creatinine_lab and isinstance(r.value, (int, float))
    )
    abs_window = timedelta(hours=rules.abs_rise_window_hours)
    points: list[tuple[datetime, float, bool]] = []
    peak: float | None = None  # highest result since the first one that met the definition
    for i, (when, value) in enumerate(series):
        earlier = series[:i]
        low_abs = min((v for t, v in earlier if when - t <= abs_window), default=None)
        low_ratio = min((v for _t, v in earlier), default=None)
        meets = (low_abs is not None and value - low_abs >= rules.abs_rise_mg_dl - 1e-9) or (
            low_ratio is not None and value >= rules.ratio * low_ratio - 1e-9
        )
        if meets:
            peak = value if peak is None else max(peak, value)
        elif peak is not None:
            peak = max(peak, value)
        active = meets or (peak is not None and value > (1 - rules.recovery_fall_fraction) * peak)
        points.append((when, value, active))
    return AkiCourse(tuple(points))


def date_aki_complications(
    complications: Iterable[dict[str, Any] | str], results: Iterable[OrderResult], admission_time: datetime
) -> list[dict[str, Any] | str]:
    """The stay's complication entries with each AKI dated by the lab (Issue
    #3642). The diagnosis is made from the creatinine, so the onset is the
    first result that meets the KDIGO definition (``aki_course``), never
    earlier than the onset the daily loop recorded; an AKI that no creatinine
    of the stay shows is not recorded (the state impact stays, and no lab is
    invented). Other complications are returned unchanged. RNG-free."""
    name = aki_response_rules().complication
    first = next((when for when, _value, meets in aki_course(results).points if meets), None)
    out: list[dict[str, Any] | str] = []
    for comp in complications:
        if not isinstance(comp, dict) or comp.get("name") != name:
            out.append(comp)
            continue
        if first is None:
            continue
        recorded = datetime.fromisoformat(comp["onset_datetime"]) if comp.get("onset_datetime") else None
        if recorded is not None and first <= recorded:
            out.append(comp)
            continue
        out.append(
            {**comp, "onset_datetime": first.isoformat(), "onset_day": (first.date() - admission_time.date()).days}
        )
    return out


@dataclass(frozen=True)
class LactateCourse:
    """The stay's lactate results ``(resulted at, mmol/L)`` in time order
    (Issue #3539). The hold begins at the first result at or above
    ``hold_at_or_above_mmol_l`` and lasts until a later result is below it."""

    points: tuple[tuple[datetime, float], ...] = ()

    def active_at(self, at: datetime) -> bool:
        """True when the latest lactate resulted at or before ``at`` is at or
        above the hold threshold."""
        threshold = aki_response_rules().lactate_hold.hold_at_or_above_mmol_l
        active = False
        for when, value in self.points:
            if when > at:
                break
            active = value >= threshold - 1e-9
        return active


def lactate_course(results: Iterable[OrderResult]) -> LactateCourse:
    """The stay's lactate results as a ``LactateCourse``."""
    lab = aki_response_rules().lactate_hold.lab
    return LactateCourse(
        tuple(
            sorted(
                (r.result_datetime, float(r.value))
                for r in results
                if r.lab_name == lab and isinstance(r.value, (int, float))
            )
        )
    )


def holds_for_lactate(drug: str) -> bool:
    """True when the drug (catalog id, name or order string) is held while the
    lactate is high."""
    return drug_key(drug) in aki_response_rules().lactate_hold.hold_drugs


def fever_persists(vitals: Iterable[VitalSignRecord]) -> bool:
    """True when a temperature of at least ``fever_celsius`` was recorded in
    the ``fever_window_hours`` up to the latest recorded vital signs."""
    rules = aki_response_rules()
    temps = [(v.timestamp, v.temperature_celsius) for v in vitals if v.temperature_celsius is not None]
    if not temps:
        return False
    since = max(t for t, _ in temps) - timedelta(hours=rules.fever_window_hours)
    return any(t > since and c >= rules.fever_celsius for t, c in temps)


def metabolic_findings_unresolved(results: Iterable[OrderResult]) -> bool:
    """True when the latest potassium is at or above the hyperkalemia treatment
    threshold or the latest total CO2 is at or below
    ``unresolved_total_co2_mmol_l`` (Issue #3830)."""
    from clinosim.modules.drug_safety.hyperkalemia import hyperkalemia_rules

    rules = aki_response_rules()
    latest: dict[str, tuple[datetime, float]] = {}
    for r in results:
        if r.lab_name in (rules.potassium_lab, rules.total_co2_lab) and isinstance(r.value, (int, float)):
            if r.lab_name not in latest or r.result_datetime >= latest[r.lab_name][0]:
                latest[r.lab_name] = (r.result_datetime, float(r.value))
    potassium = latest.get(rules.potassium_lab)
    co2 = latest.get(rules.total_co2_lab)
    return bool(
        (potassium is not None and potassium[1] >= hyperkalemia_rules().treat_threshold_mmol_l)
        or (co2 is not None and co2[1] <= rules.unresolved_total_co2_mmol_l)
    )


def discharge_findings_unresolved(
    course: AkiCourse, vitals: Iterable[VitalSignRecord], results: Iterable[OrderResult] = ()
) -> bool:
    """True while the patient is not fit to go home for the kidneys or a
    fever: AKI that has not begun to recover, a fever in the last day, or the
    potassium / total CO2 of kidney failure (Issue #3830)."""
    return course.not_improving or fever_persists(vitals) or metabolic_findings_unresolved(results)


def discharge_extension_days(
    course: AkiCourse, vitals: Iterable[VitalSignRecord], results: Iterable[OrderResult] = ()
) -> int:
    """How many days past the sampled stay the patient may be kept for the
    findings still unresolved (Issue #3637): ``fever_max_extension_days`` while
    a fever persists, ``max_extension_days`` for AKI that has not begun to
    recover or metabolic findings that persist, 0 when nothing is unresolved."""
    rules = aki_response_rules()
    vitals = list(vitals)
    if fever_persists(vitals):
        return rules.fever_max_extension_days
    return rules.max_extension_days if course.not_improving or metabolic_findings_unresolved(results) else 0


def _field(rec: object, name: str) -> object:
    return rec.get(name) if isinstance(rec, dict) else getattr(rec, name, None)


def _when(value: object) -> datetime | None:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if isinstance(value, datetime) else None


def _results_from_records(records: Iterable[object]) -> list[OrderResult]:
    results: list[OrderResult] = []
    for rec in records:
        when, value = _when(_field(rec, "result_datetime")), _field(rec, "value")
        if when is not None and isinstance(value, (int, float)):
            results.append(OrderResult(result_datetime=when, lab_name=str(_field(rec, "lab_name") or ""), value=value))
    return results


def _course_from_records(records: Iterable[object]) -> AkiCourse:
    return aki_course(_results_from_records(records))


def aki_active_from_records(records: Iterable[object]) -> bool:
    """Whether the final creatinine of ``records`` (``OrderResult`` objects or
    their JSON dicts) meets the AKI definition — the discharge instructions'
    gate (``applies_when: {aki_at_discharge: true}``)."""
    return _course_from_records(records).active


def _vitals_from_records(records: Iterable[object]) -> list[VitalSignRecord]:
    vitals: list[VitalSignRecord] = []
    for rec in records:
        when, temp = _when(_field(rec, "timestamp")), _field(rec, "temperature_celsius")
        if when is not None and isinstance(temp, (int, float)):
            vitals.append(VitalSignRecord(timestamp=when, temperature_celsius=float(temp)))
    return vitals


def fever_persists_from_records(vital_records: Iterable[object]) -> bool:
    """``fever_persists`` over recorded vital signs (objects or JSON dicts)."""
    return fever_persists(_vitals_from_records(vital_records))


def discharge_findings_unresolved_from_records(lab_records: Iterable[object], vital_records: Iterable[object]) -> bool:
    """``discharge_findings_unresolved`` over a stay's recorded creatinine
    results and vital signs (objects or their JSON dicts): True when the stay
    ended with AKI not recovering or a fever in the last day, i.e. it was
    discharged at the deferral cap rather than because the gate was met."""
    results = _results_from_records(lab_records)
    return discharge_findings_unresolved(aki_course(results), _vitals_from_records(vital_records), results)


def metabolic_findings_unresolved_from_records(lab_records: Iterable[object]) -> bool:
    """``metabolic_findings_unresolved`` over recorded lab results (objects or
    their JSON dicts)."""
    return metabolic_findings_unresolved(_results_from_records(lab_records))
