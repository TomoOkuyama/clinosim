"""Vaccination visits record the vaccines given at them (Issue #2868).

The healthcare calendar schedules vaccination visits (the seasonal flu
visit, the pediatric immunization visits) and the immunization engine
draws the patient's doses on its own calendar. This pass binds the two
before the generic ±60-day alignment: a visit coded Z23 records the doses
given at it (``encounter_id`` = the visit, ``occurrence_date`` = the visit
date), so the dose is not charted on another day or on a synthesised
``ENC-VAX-*`` encounter.

- Flu: the season's flu dose is given at the season's first flu visit
  (the engine's dose re-dated, or a new one when the engine drew none);
  every other flu record of that season (a second dose, a refusal) is
  dropped. In a season the calendar covered, a person it offers flu
  visits to (``is_flu_vaccination_candidate``) and who had none gets no
  off-visit flu dose: the visit draw is the season's vaccination
  decision for them, so the two draws do not add up to the union of two
  calibrated rates. A season keeps at most one flu record (a dose, or
  else a refusal).
- Pediatric immunization visits: the series doses whose age window holds
  the visit age are given at the visit, earliest visit first. A dose the
  engine did not draw is added when the series is on track (dose 1, or
  the previous dose already given).

Deterministic, draws nothing.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import set_attr_or_key as _set
from clinosim.modules.immunization.engine import (
    _age_on,
    _coverage,
    _parse,
    flu_season_of,
    product_cvx,
    synthetic_lot_number,
)

IMMUNIZATION_VISIT_DX = "Z23"
"""ICD-10 / ICD-10-CM "Encounter for immunization" — the reason code of a
vaccination visit."""

FLU_VISIT_CONDITION = "flu_vaccination"
"""Encounter condition YAML of the seasonal flu vaccination visit."""

VAX_ENCOUNTER_PREFIX = "ENC-VAX-"
"""Id prefix of the vaccination encounters the enricher synthesises."""


@dataclass(frozen=True)
class VaccinationVisit:
    """An outpatient visit held for vaccination (reason Z23)."""

    encounter_id: str
    day: date
    is_flu: bool


@lru_cache(maxsize=1)
def _flu_visit_chief_complaints() -> frozenset[str]:
    """Every language's chief complaint of the flu vaccination visit."""
    from clinosim.modules.encounter.protocol import load_encounter_condition

    chief = load_encounter_condition(FLU_VISIT_CONDITION).get("chief_complaint") or {}
    values = chief.values() if isinstance(chief, dict) else [chief]
    return frozenset(str(v) for v in values if v)


def _is_outpatient(enc: Any) -> bool:
    et = _get(enc, "encounter_type", "")
    return str(getattr(et, "value", et)).lower() in ("outpatient", "amb", "ambulatory")


def vaccination_visits_by_patient(records: list) -> dict[str, list[VaccinationVisit]]:
    """Each patient's vaccination visits across all their records, by date.

    A visit's reason is the encounter's own admission diagnosis, else its
    record's (one outpatient visit per record).
    """
    flu_chiefs = _flu_visit_chief_complaints()
    out: dict[str, dict[str, VaccinationVisit]] = {}
    for rec in records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        if not pid:
            continue
        rec_dx = _get(_get(rec, "clinical_diagnosis", None), "admission_diagnosis_code", "") or ""
        for enc in _get(rec, "encounters", []) or []:
            eid = str(_get(enc, "encounter_id", "") or "")
            adm = _get(enc, "admission_datetime", None)
            if not eid or eid.startswith(VAX_ENCOUNTER_PREFIX) or adm is None or not _is_outpatient(enc):
                continue
            if (_get(enc, "admission_diagnosis_code", "") or rec_dx) != IMMUNIZATION_VISIT_DX:
                continue
            chiefs = {_get(enc, "chief_complaint", "") or "", _get(enc, "chief_complaint_ja", "") or ""}
            out.setdefault(pid, {})[eid] = VaccinationVisit(eid, adm.date(), bool(chiefs & flu_chiefs))
    return {pid: sorted(v.values(), key=lambda x: (x.day, x.encounter_id)) for pid, v in out.items()}


def is_flu_visit_candidate(patient: Any) -> bool:
    """Whether the healthcare calendar offers ``patient`` flu vaccination
    visits (``population.is_flu_vaccination_candidate``)."""
    from clinosim.modules.population import is_flu_vaccination_candidate

    age = int(_get(patient, "age", 0) or 0)
    return is_flu_vaccination_candidate(age, len(_get(patient, "chronic_conditions", []) or []))


def _cvx_codes(vaccine: dict) -> frozenset[str]:
    return frozenset({str(vaccine["cvx"])} | {str(p["cvx"]) for p in vaccine.get("products") or []})


def flu_season_months(schedule: dict) -> dict[str, frozenset[int]]:
    """CVX → the months a dose of that annual (flu) vaccine is given in."""
    out: dict[str, frozenset[int]] = {}
    for v in schedule.values():
        if v.get("frequency") != "annual":
            continue
        months = frozenset(int(m) for m in (v.get("seasonal_distribution") or {})) or frozenset(
            {int(v.get("season_month", 10))}
        )
        for cvx in _cvx_codes(v):
            out.setdefault(cvx, months)
    return out


def _completed(imm: Any) -> bool:
    return (_get(imm, "status", "completed") or "completed") == "completed"


def _give_at(imm: Any, vaccine: dict, visit: VaccinationVisit) -> None:
    """Re-date ``imm`` to ``visit`` and bind it there."""
    _set(imm, "occurrence_date", visit.day)
    _set(imm, "encounter_id", visit.encounter_id)
    _set(imm, "vaccine_cvx", product_cvx(vaccine, visit.day))
    _set(imm, "primary_source", True)
    if _completed(imm):
        _set(imm, "lot_number", synthetic_lot_number(str(vaccine["cvx"]), visit.day))


def _new_dose(vaccine: dict, visit: VaccinationVisit, nurse: str, dose_number: int | None = None) -> Any:
    from clinosim.types.encounter import ImmunizationRecord

    return ImmunizationRecord(
        vaccine_cvx=product_cvx(vaccine, visit.day),
        occurrence_date=visit.day,
        administered_by=nurse,
        lot_number=synthetic_lot_number(str(vaccine["cvx"]), visit.day),
        dose_number=dose_number,
        encounter_id=visit.encounter_id,
    )


def _flu_vaccine_for(annual: list[dict], age: int, sex: str) -> dict:
    """The annual vaccine for a patient of ``age``: one the patient is
    covered by, else one they are old enough for, else the first."""
    covered = [v for v in annual if int(v["min_age"]) <= age and _coverage(v.get("coverage_by_age_sex", {}), age, sex)]
    old_enough = [v for v in annual if int(v["min_age"]) <= age]
    return (covered or old_enough or annual)[0]


def _calendar_covers_season(season: int, sim_start: date | None, as_of: date) -> bool:
    """Whether the healthcare calendar ran the whole flu-visit window of
    ``season`` (its October-December months fall inside the simulation)."""
    from clinosim.modules.population import FLU_VAX_MONTHS

    if sim_start is None:
        return False
    first_month, last_month = min(FLU_VAX_MONTHS), max(FLU_VAX_MONTHS)
    first = date(season, first_month, 1)
    last = date(season, last_month, calendar.monthrange(season, last_month)[1])
    return sim_start <= first and last <= as_of


def _bind_flu(
    imms: list,
    visits: list[VaccinationVisit],
    patient: Any,
    schedule: dict,
    *,
    as_of: date,
    sim_start: date | None,
    flu_visit_candidate: bool,
    nurse: str,
) -> list:
    annual = [v for v in schedule.values() if v.get("frequency") == "annual"]
    if not annual:
        return imms
    vaccine_of: dict[str, dict] = {}
    for v in annual:
        for cvx in _cvx_codes(v):
            vaccine_of.setdefault(cvx, v)
    flu_by_season: dict[int, list] = {}
    rest: list = []
    for imm in imms:
        occ = _get(imm, "occurrence_date", None)
        if str(_get(imm, "vaccine_cvx", "")) in vaccine_of and isinstance(occ, date):
            flu_by_season.setdefault(flu_season_of(occ), []).append(imm)
        else:
            rest.append(imm)
    first_visit: dict[int, VaccinationVisit] = {}
    for v in visits:
        if v.is_flu:
            first_visit.setdefault(flu_season_of(v.day), v)
    dob = _get(patient, "date_of_birth", None)
    base_age = int(_get(patient, "age", 0) or 0)
    sex = _get(patient, "sex", "M") or "M"

    for season in sorted(set(flu_by_season) | set(first_visit)):
        records = flu_by_season.get(season, [])
        done = [r for r in records if _completed(r)]
        refused = [r for r in records if not _completed(r)]
        visit = first_visit.get(season)
        if visit is not None:
            if done:
                dose = done[0]
                _give_at(dose, vaccine_of[str(_get(dose, "vaccine_cvx", ""))], visit)
            else:
                vaccine = _flu_vaccine_for(annual, _age_on(dob, visit.day, base_age), sex)
                dose = _new_dose(vaccine, visit, nurse)
            rest.append(dose)
        elif done and not (flu_visit_candidate and _calendar_covers_season(season, sim_start, as_of)):
            rest.append(done[0])
        elif refused:
            rest.append(refused[0])
    return rest


def _bind_pediatric(imms: list, visits: list[VaccinationVisit], patient: Any, schedule: dict, nurse: str) -> list:
    dob = _get(patient, "date_of_birth", None)
    if not isinstance(dob, date):
        return imms
    series = [
        (v, dose)
        for v in schedule.values()
        if v.get("frequency") == "pediatric_series"
        for dose in v.get("doses") or []
    ]
    imms = list(imms)
    hosted: set[int] = set()

    def _is(imm: Any, vaccine: dict, dose_number: int | None) -> bool:
        return _get(imm, "dose_number", None) == dose_number and str(_get(imm, "vaccine_cvx", "")) in _cvx_codes(
            vaccine
        )

    def _same_series(imm: Any, vaccine: dict) -> bool:
        return _get(imm, "dose_number", None) is not None and str(_get(imm, "vaccine_cvx", "")) in _cvx_codes(vaccine)

    for visit in visits:
        if visit.is_flu:
            continue
        age_days = (visit.day - dob).days
        given_here: set[int] = set()  # one dose of a series per visit
        for vaccine, dose in series:
            if id(vaccine) in given_here or not int(dose["age_days_min"]) <= age_days <= int(dose["age_days_max"]):
                continue
            if _parse(str(vaccine["available_from"])) > visit.day:
                continue
            dose_number = int(dose.get("dose_number", 0)) or 1
            others = [i for i in imms if _same_series(i, vaccine) and not _is(i, vaccine, dose_number)]
            # The series stays in order: earlier doses before the visit,
            # later ones after it.
            if any((_get(i, "dose_number") < dose_number) != (_get(i, "occurrence_date") < visit.day) for i in others):
                continue
            existing = next((i for i in imms if _is(i, vaccine, dose_number)), None)
            if existing is not None:
                # Bound elsewhere already (another visit, an inpatient stay).
                if id(existing) in hosted or _get(existing, "encounter_id", ""):
                    continue
                _give_at(existing, vaccine, visit)
                hosted.add(id(existing))
                given_here.add(id(vaccine))
                continue
            on_track = dose_number == 1 or any(_is(i, vaccine, dose_number - 1) and _completed(i) for i in others)
            if on_track:
                new = _new_dose(vaccine, visit, nurse, dose_number)
                imms.append(new)
                hosted.add(id(new))
                given_here.add(id(vaccine))
    return imms


def bind_to_vaccination_visits(
    imms: list,
    visits: list[VaccinationVisit],
    patient: Any,
    schedule: dict,
    *,
    as_of: date,
    sim_start: date | None,
    flu_visit_candidate: bool,
    nurse: str = "",
) -> list:
    """Give the doses at the patient's vaccination visits (module docstring).

    ``flu_visit_candidate``: the healthcare calendar offers this patient
    flu vaccination visits (``is_flu_visit_candidate``). Returns the
    patient's immunization list, sorted by date.
    """
    imms = _bind_flu(
        imms,
        visits,
        patient,
        schedule,
        as_of=as_of,
        sim_start=sim_start,
        flu_visit_candidate=flu_visit_candidate,
        nurse=nurse,
    )
    if visits:
        imms = _bind_pediatric(imms, visits, patient, schedule, nurse)
    imms.sort(key=lambda r: _get(r, "occurrence_date", date.min))
    return imms
