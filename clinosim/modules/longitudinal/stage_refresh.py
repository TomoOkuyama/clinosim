"""Chronic stages from the latest labs (Issue #3273).

The longitudinal engine draws a chronic condition's stage once a year, apart
from the labs the simulation then produces, so a record's stored stage could
read "CKD G3a" beside an eGFR of 27. ``refresh_stages_from_labs`` is a
post-records pass that restates each record's staged conditions from the
latest result of the stage's lab known by the end of that record: the CKD G
category of the latest eGFR (an N18 problem) and the HbA1c of a diabetes
problem whose stage is an HbA1c. It draws no random number; thresholds and
formats are in ``modules/longitudinal/reference_data/stage_from_labs.yaml``.
"""

from __future__ import annotations

import dataclasses
import functools
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.datafiles import load_data_yaml
from clinosim.timeutil import parse_iso_datetime

_YAML = Path(__file__).resolve().parent / "reference_data" / "stage_from_labs.yaml"


class _Stage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_egfr: float = Field(ge=0)
    stage: str


class _Ckd(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    icd_base: str
    lab: str
    creatinine_lab: str
    creatinine_unit: str
    format: str
    stages: list[_Stage] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> _Ckd:
        bounds = [s.min_egfr for s in self.stages]
        if bounds != sorted(bounds, reverse=True) or bounds[-1] != 0:
            raise ValueError("ckd stages must descend and end at min_egfr 0")
        return self


class _Hba1c(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lab: str
    prefix: str
    decimals: int = Field(ge=0)


class StageFromLabs(BaseModel):
    """Shape of stage_from_labs.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: dict[str, Any] = Field(default_factory=dict)
    ckd: _Ckd
    hba1c: _Hba1c


@functools.cache
def stage_from_labs_rules() -> StageFromLabs:
    """The validated ``stage_from_labs.yaml`` (shared, read-only)."""
    return StageFromLabs.model_validate(load_data_yaml(_YAML))


def ckd_g_category(egfr: float) -> str:
    """The KDIGO CKD G category ("G3a") of an eGFR (mL/min/1.73 m2)."""
    stages = stage_from_labs_rules().ckd.stages
    for row in stages:
        if egfr >= row.min_egfr:
            return row.stage
    return stages[-1].stage


def ckd_stage_label(egfr: float) -> str:
    """The stored stage label ("CKD G3a") of an eGFR."""
    return stage_from_labs_rules().ckd.format.format(stage=ckd_g_category(egfr))


def _age_at(patient: Any, at: datetime) -> int | None:
    """The patient's age in years at ``at`` (from the date of birth, else the
    stored age)."""
    dob = _get(patient, "date_of_birth", None)
    if dob is not None and hasattr(dob, "year"):
        return int(at.year - dob.year - ((at.month, at.day) < (dob.month, dob.day)))
    age = _get(patient, "age", None)
    return int(age) if isinstance(age, (int, float)) else None


def creatinine_egfr(patient: Any, creatinine: Any, at: datetime, unit: Any = None) -> float | None:
    """The eGFR (mL/min/1.73 m2) of a serum creatinine result at ``at`` with
    the patient's country equation (Issue #3466): the single derivation the
    stage refresh and the narrative share. ``None`` when the value or unit is
    not a creatinine in the unit the rule names, or the patient's age / height
    is outside what the equation covers."""
    from clinosim.modules.physiology.egfr import estimated_gfr

    rules = stage_from_labs_rules().ckd
    if isinstance(creatinine, bool) or not isinstance(creatinine, (int, float)):
        return None
    if unit and str(unit).strip().lower() != rules.creatinine_unit.lower():
        return None
    age = _age_at(patient, at)
    if age is None:
        return None
    address = _get(patient, "address", None)
    country = str(_get(address, "country", "") or "US")
    egfr = estimated_gfr(
        float(creatinine), age, str(_get(patient, "sex", "") or ""), _get(patient, "height_cm", None), country
    )
    return None if egfr is None else round(egfr, 1)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _naive(value: Any) -> datetime | None:
    at = value if isinstance(value, datetime) else parse_iso_datetime(value, lenient=True)
    return at.replace(tzinfo=None) if at is not None else None


def _record_start(record: Any) -> datetime:
    encounters = _get(record, "encounters", []) or []
    at = _naive(_get(encounters[0], "admission_datetime", None)) if encounters else None
    return at or datetime.min


def restated_stage(condition: Any, latest: dict[str, float]) -> str | None:
    """The stage the latest labs (``{lab name: value}``) state for
    ``condition``, ``None`` when no lab states it (the stored stage stays)."""
    rules = stage_from_labs_rules()
    code = str(_get(condition, "code", "") or "")
    stored = str(_get(condition, "stage", "") or "")
    if code.upper().startswith(rules.ckd.icd_base) and rules.ckd.lab in latest:
        return ckd_stage_label(latest[rules.ckd.lab])
    if stored.startswith(rules.hba1c.prefix) and rules.hba1c.lab in latest:
        return f"{rules.hba1c.prefix} {latest[rules.hba1c.lab]:.{rules.hba1c.decimals}f}%"
    return None


def refresh_stages_from_labs(ctx: Any) -> None:
    """Post-records enricher: restate each record's staged conditions from the
    latest lab results of the patient known by the end of the record. A record
    whose patient has no such lab keeps its stage; a record's patient object
    is replaced by a copy, never mutated in place (profiles may be shared)."""
    from clinosim.modules.observation.engine import canonical_lab_name

    rules = stage_from_labs_rules()
    labs_wanted = {rules.ckd.lab, rules.hba1c.lab}
    by_patient: dict[str, list[Any]] = {}
    for record in ctx.records:
        patient = _get(record, "patient", None)
        if patient is not None:
            by_patient.setdefault(str(_get(patient, "patient_id", "") or ""), []).append(record)
    for records in by_patient.values():
        records.sort(key=_record_start)
        results: dict[str, list[tuple[datetime, float]]] = {}
        derived: list[tuple[datetime, float]] = []
        for record in records:
            for lab in _get(record, "lab_results", []) or []:
                name = str(_get(lab, "lab_name", "") or "")
                value = _get(lab, "value", None)
                at = _naive(_get(lab, "result_datetime", None))
                if name in labs_wanted and at is not None and isinstance(value, (int, float)):
                    results.setdefault(name, []).append((at, float(value)))
                elif canonical_lab_name(name) == rules.ckd.creatinine_lab and at is not None:
                    egfr = creatinine_egfr(_get(record, "patient", None), value, at, _get(lab, "unit", None))
                    if egfr is not None:
                        derived.append((at, egfr))
        # A creatinine-derived eGFR joins the eGFR series; a measured eGFR at
        # the same time wins (Issue #3466).
        measured = {r[0] for r in results.get(rules.ckd.lab, [])}
        results.setdefault(rules.ckd.lab, []).extend(r for r in derived if r[0] not in measured)
        if not results[rules.ckd.lab]:
            del results[rules.ckd.lab]
        for record in records:
            end = _record_end(record)
            latest = {
                name: max((r for r in rows if r[0] <= end), default=None, key=lambda r: r[0])
                for name, rows in results.items()
            }
            known = {name: row[1] for name, row in latest.items() if row is not None}
            if not known:
                continue
            patient = record.patient
            conditions = list(_get(patient, "chronic_conditions", []) or [])
            changed = False
            for i, cond in enumerate(conditions):
                stage = restated_stage(cond, known)
                if stage is not None and stage != _get(cond, "stage", ""):
                    conditions[i] = dataclasses.replace(cond, stage=stage)
                    changed = True
            if changed:
                record.patient = dataclasses.replace(patient, chronic_conditions=conditions)


def _record_end(record: Any) -> datetime:
    encounters = _get(record, "encounters", []) or []
    ends = [
        _naive(_get(e, "discharge_datetime", None)) or _naive(_get(e, "admission_datetime", None)) for e in encounters
    ]
    lab_times = [_naive(_get(lab, "result_datetime", None)) for lab in _get(record, "lab_results", []) or []]
    candidates = [t for t in (*ends, *lab_times) if t is not None]
    return max(candidates) if candidates else datetime.max
