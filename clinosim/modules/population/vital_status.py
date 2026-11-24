"""Vital status — the single place deaths are recorded and propagated (Issue #2166).

``PersonRecord.date_of_death`` / ``death_place`` is the source of truth for a
person's death. This module holds the two operations around it that the
simulator needs:

* :func:`record_hospital_death` — called by the inpatient dispatchers when a
  simulated stay ends in death. The expired encounter's discharge is the
  time of death (Issue #2984) and its date the death date.
* :func:`death_counts_by_place` — the run's deaths by place, logged at the end
  of the run so the in-hospital / community split can be calibrated.
* :func:`sync_profile_death_dates` — called once after all records exist.
  Every ``PatientProfile`` of the person (including profiles activated before
  the death, which are shared with earlier records) gets the same death date
  and time, so ``Patient.deceasedDateTime`` agrees across encounters.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.types.output import CIFPatientRecord
from clinosim.types.population import PersonRecord

__all__ = [
    "death_counts_by_place",
    "defer_death_past_stay",
    "known_death_date",
    "record_hospital_death",
    "sync_profile_death_dates",
]

# Issue #3633: a death moved past a stay it fell inside lands this many days
# after the discharge (drawn uniformly from a dedicated sub-seed).
DEATH_DEFERRAL_MIN_DAYS = 1
DEATH_DEFERRAL_MAX_DAYS = 30


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
    at = final.discharge_datetime if isinstance(final.discharge_datetime, datetime) else None
    # Issue #3633: a community death date inside this stay is replaced by the
    # stay's own death, even when the stay's death falls a day after it.
    dod = person.date_of_death
    if dod is not None and person.death_place == "community" and _as_date(final.admission_datetime) < dod:
        person.date_of_death = None
        person.death_place = None
        person.death_datetime = None
    person.record_death(when, "hospital", at=at)
    return when


def known_death_date(person: PersonRecord, cutoff: date | None) -> date | None:
    """The person's death date as far as the run knows it (Issue #3633).

    A community death after ``cutoff`` (the snapshot or window end) is not known
    to the record yet, so a stay must not end in it (the same rule as
    :func:`sync_profile_death_dates`).
    """
    dod = person.date_of_death
    if dod is None or (cutoff is not None and dod > cutoff and person.death_place != "hospital"):
        return None
    return dod


def defer_death_past_stay(person: PersonRecord, record: CIFPatientRecord, master_seed: int) -> bool:
    """Move a community death out of a survivor stay it falls inside (Issue #3633).

    For a stay without a modelled death course: when the person's death date is
    after the admission date and before the discharge date of a stay that ended
    in a discharge, the death moves to a day after the discharge (1 to
    ``DEATH_DEFERRAL_MAX_DAYS`` days, from a sub-seed of the person and the
    discharge, so the draw is independent of every other stream). Returns True
    when the death was moved.
    """
    from clinosim.seeding import PHASE_DEATH_DEFERRAL, derive_phase_rng

    dod = person.date_of_death
    if dod is None or record.deceased or person.death_place != "community":
        return False
    for enc in record.encounters:
        if enc.discharge_datetime is None:
            continue
        discharge = _as_date(enc.discharge_datetime)
        if _as_date(enc.admission_datetime) < dod < discharge:
            rng = derive_phase_rng(master_seed, PHASE_DEATH_DEFERRAL, f"{person.person_id}|{discharge.isoformat()}")
            gap = int(rng.integers(DEATH_DEFERRAL_MIN_DAYS, DEATH_DEFERRAL_MAX_DAYS + 1))
            person.date_of_death = discharge + timedelta(days=gap)
            person.death_datetime = None
            return True
    return False


def sync_profile_death_dates(
    records: Iterable[CIFPatientRecord],
    population: object,
    as_of: date | None,
) -> None:
    """Copy each person's recorded death onto every one of their profiles.

    Community deaths after ``as_of`` (the snapshot or window end) are not yet
    known to the record and are cleared from the profile. In-hospital deaths
    are always kept: the expired stay itself is in the CIF. ``population`` is a
    ``PopulationRegistry`` (typed loosely to avoid an import cycle).
    """
    persons = getattr(population, "persons", {})
    for record in records:
        person = persons.get(record.patient.patient_id)
        if person is None:
            continue
        dod = person.date_of_death
        death_dt = person.death_datetime
        # A community death after the cutoff is not yet known; an
        # in-hospital death is, because its expired stay is in the CIF.
        if dod is not None and as_of is not None and dod > as_of and person.death_place != "hospital":
            dod = death_dt = None
        record.patient.date_of_death = dod
        record.patient.death_datetime = death_dt


def death_counts_by_place(population: object, start: date, end: date) -> dict[str, int]:
    """Count deaths dated within ``[start, end]`` by ``death_place``."""
    counts = {"hospital": 0, "community": 0}
    for person in getattr(population, "persons", {}).values():
        dod = person.date_of_death
        if dod is not None and start <= dod <= end and person.death_place in counts:
            counts[person.death_place] += 1
    return counts
