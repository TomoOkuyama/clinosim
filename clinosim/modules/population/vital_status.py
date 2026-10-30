"""Vital status — the single place deaths are recorded and propagated (Issue #2166).

``PersonRecord.date_of_death`` / ``death_place`` is the source of truth for a
person's death. This module holds the two operations around it that the
simulator needs:

* :func:`record_hospital_death` — called by the inpatient dispatchers when a
  simulated stay ends in death. The expired encounter's discharge date is the
  death date.
* :func:`death_counts_by_place` — the run's deaths by place, logged at the end
  of the run so the in-hospital / community split can be calibrated.
* :func:`sync_profile_death_dates` — called once after all records exist.
  Every ``PatientProfile`` of the person (including profiles activated before
  the death, which are shared with earlier records) gets the same death date,
  so ``Patient.deceasedDateTime`` agrees across encounters.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.types.output import CIFPatientRecord
from clinosim.types.population import PersonRecord

__all__ = ["death_counts_by_place", "record_hospital_death", "sync_profile_death_dates"]


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def record_hospital_death(person: PersonRecord, record: CIFPatientRecord) -> date | None:
    """Record an in-hospital death from ``record`` on ``person``.

    Returns the death date, or ``None`` when the record did not end in death.
    The death date is the discharge of the expired encounter (falling back to
    the last discharge in the record when no encounter carries the expired
    disposition).
    """
    if not record.deceased:
        return None
    discharges = [e for e in record.encounters if e.discharge_datetime is not None]
    if not discharges:
        return None
    expired = [e for e in discharges if e.discharge_disposition == DischargeDisposition.EXP]
    final = (expired or discharges)[-1]
    assert final.discharge_datetime is not None
    when = _as_date(final.discharge_datetime)
    person.record_death(when, "hospital")
    return when


def sync_profile_death_dates(
    records: Iterable[CIFPatientRecord],
    population: object,
    as_of: date | None,
) -> None:
    """Copy each person's recorded death onto every one of their profiles.

    Deaths after ``as_of`` (the snapshot or window end) are not yet known to
    the record and are cleared from the profile. ``population`` is a
    ``PopulationRegistry`` (typed loosely to avoid an import cycle).
    """
    persons = getattr(population, "persons", {})
    for record in records:
        person = persons.get(record.patient.patient_id)
        if person is None:
            continue
        dod = person.date_of_death
        if dod is not None and as_of is not None and dod > as_of:
            dod = None
        record.patient.date_of_death = dod


def death_counts_by_place(population: object, start: date, end: date) -> dict[str, int]:
    """Count deaths dated within ``[start, end]`` by ``death_place``."""
    counts = {"hospital": 0, "community": 0}
    for person in getattr(population, "persons", {}).values():
        dod = person.date_of_death
        if dod is not None and start <= dod <= end and person.death_place in counts:
            counts[person.death_place] += 1
    return counts
