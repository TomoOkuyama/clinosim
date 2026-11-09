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
  the previous dose already given). A dose charted on the visit's day at
  another, non-vaccination encounter moves to the visit. A visit that
  gives nothing (the child has not kept up the series, which is not
  restarted out of order) documents the due dose as ``not-done``, so a
  vaccination visit always records an Immunization (Issue #2974).

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
    dose_intervals_by_cvx,
    flu_season_of,
    licensed_on,
    product_cvx,
    series_allows,
    synthetic_lot_number,
)

IMMUNIZATION_VISIT_DX = "Z23"
"""ICD-10 / ICD-10-CM "Encounter for immunization" — the reason code of a
vaccination visit."""


def vaccination_visit_reason_codes(country: str, cvx_codes: Any) -> list[str]:
    """The diagnosis codes of a vaccination visit's reason in ``country``'s
    system (Issue #3008). ICD-10-CM (US) codes every such visit
    ``IMMUNIZATION_VISIT_DX``; WHO ICD-10 (JP) has one "need for immunization"
    code per disease group (Z23 bacterial, Z24 / Z25 viral, Z26 other, Z27
    combinations), so a JP visit gets the code of each vaccine given, in
    order, from ``locale/jp/code_mapping_vaccination_reason.yaml`` — the
    table's ``unspecified`` code when no given vaccine is listed."""
    from clinosim.locale.loader import load_code_mapping

    table: dict[str, Any] = dict(load_code_mapping("vaccination_reason", country) or {})
    by_cvx = table.get("by_cvx") if isinstance(table.get("by_cvx"), dict) else {}
    if not by_cvx:
        return [IMMUNIZATION_VISIT_DX]
    codes: list[str] = []
    for cvx in cvx_codes or ():
        code = str(by_cvx.get(str(cvx), "") or "")
        if code and code not in codes:
            codes.append(code)
    return codes or [str(table.get("unspecified") or IMMUNIZATION_VISIT_DX)]


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


def _flu_vaccine_for(annual: list[dict], dob: date | None, day: date, base_age: int, sex: str) -> dict | None:
    """The annual vaccine given on ``day``: one the patient is covered by,
    else one they are old enough for, else the first. Only vaccines past
    their licensure floor on ``day`` count (Issue #2979: no flu dose before
    6 months); ``None`` when there is none."""
    licensed = [v for v in annual if licensed_on(v, dob, day)]
    age = _age_on(dob, day, base_age)
    covered = [
        v for v in licensed if int(v["min_age"]) <= age and _coverage(v.get("coverage_by_age_sex", {}), age, sex)
    ]
    old_enough = [v for v in licensed if int(v["min_age"]) <= age]
    return next(iter(covered or old_enough or licensed), None)


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
    dob = _get(patient, "date_of_birth", None)
    base_age = int(_get(patient, "age", 0) or 0)
    sex = _get(patient, "sex", "M") or "M"
    # Issue #2979: a flu visit before the patient may have any flu vaccine
    # (6 months) gives none.
    first_visit: dict[int, VaccinationVisit] = {}
    for v in visits:
        if v.is_flu and any(licensed_on(a, dob, v.day) for a in annual):
            first_visit.setdefault(flu_season_of(v.day), v)

    for season in sorted(set(flu_by_season) | set(first_visit)):
        records = flu_by_season.get(season, [])
        done = [r for r in records if _completed(r)]
        refused = [r for r in records if not _completed(r)]
        visit = first_visit.get(season)
        if visit is not None:
            # Only visits past a licensure floor are kept, so a vaccine exists.
            vaccine = _flu_vaccine_for(annual, dob, visit.day, base_age, sex)
            if done:
                dose = done[0]
                drawn = vaccine_of[str(_get(dose, "vaccine_cvx", ""))]
                _give_at(dose, drawn if licensed_on(drawn, dob, visit.day) else vaccine or drawn, visit)
            elif vaccine is not None:
                dose = _new_dose(vaccine, visit, nurse)
            else:
                continue
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
    visit_ids = {v.encounter_id for v in visits}
    # Issue #3006: a visit gives a dose only where the series' interval
    # rules allow it (a visit inside the next dose's age window can come too
    # soon after the previous dose: the JP windows touch).
    intervals = dose_intervals_by_cvx(schedule)

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
                # Bound elsewhere already (another vaccination visit, an
                # inpatient stay). A dose charted on this visit's day at
                # another encounter (a same-day well-child visit) is given
                # here, at the visit held for it (Issue #2974).
                bound_to = str(_get(existing, "encounter_id", "") or "")
                same_day_elsewhere = (
                    bound_to
                    and bound_to not in visit_ids
                    and _get(existing, "occurrence_date", None) == visit.day
                    and id(existing) not in hosted
                )
                if (id(existing) in hosted or bound_to) and not same_day_elsewhere:
                    continue
                if not series_allows(existing, visit.day, imms, intervals.get(str(vaccine["cvx"]))):
                    continue
                _give_at(existing, vaccine, visit)
                hosted.add(id(existing))
                given_here.add(id(vaccine))
                continue
            on_track = dose_number == 1 or any(_is(i, vaccine, dose_number - 1) and _completed(i) for i in others)
            if on_track:
                new = _new_dose(vaccine, visit, nurse, dose_number)
                if not series_allows(new, visit.day, imms, intervals.get(str(vaccine["cvx"]))):
                    continue
                imms.append(new)
                hosted.add(id(new))
                given_here.add(id(vaccine))
        if not given_here:
            _chart_not_done(imms, visit, series, age_days, hosted)
    return imms


def _chart_not_done(imms: list, visit: VaccinationVisit, series: list, age_days: int, hosted: set[int]) -> None:
    """A vaccination visit that gives nothing documents the due dose as not
    done (Issue #2974): the visit was held, the dose was not given (a series
    the child has not kept up is not restarted out of order). The first
    series dose due at the visit age without a given dose is charted; a
    visit at which every due dose was already given charts nothing."""
    for vaccine, dose in series:
        if not int(dose["age_days_min"]) <= age_days <= int(dose["age_days_max"]):
            continue
        if _parse(str(vaccine["available_from"])) > visit.day:
            continue
        dose_number = int(dose.get("dose_number", 0)) or 1
        cvx = _cvx_codes(vaccine)
        same = [
            i for i in imms if _get(i, "dose_number", None) == dose_number and str(_get(i, "vaccine_cvx", "")) in cvx
        ]
        if any(_completed(i) for i in same):
            continue
        refusal = next((i for i in same if id(i) not in hosted and not _get(i, "encounter_id", "")), None)
        if refusal is None:
            from clinosim.types.encounter import ImmunizationRecord

            refusal = ImmunizationRecord(
                vaccine_cvx=product_cvx(vaccine, visit.day), status="not-done", dose_number=dose_number
            )
            imms.append(refusal)
        _give_at(refusal, vaccine, visit)
        hosted.add(id(refusal))
        return


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
