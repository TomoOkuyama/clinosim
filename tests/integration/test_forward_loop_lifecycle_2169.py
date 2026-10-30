"""Forward loop lifecycle invariants on a small cohort (Issue #2169).

A newborn joins the population at birth-stay discharge and from then on is
simulated like everyone else; nobody has an encounter that starts after
their death.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def dataset():
    return run_beta(
        SimulatorConfig(country="US", catchment_population=1500, random_seed=7, time_range=("2024-01-01", "2025-12-31"))
    )


def _day(value):
    return value.date() if isinstance(value, datetime) else value


def test_newborns_get_visits_after_the_birth_stay(dataset) -> None:
    birth_discharge = {}
    for r in dataset.patients:
        for e in r.encounters:
            if str(getattr(e.admit_source, "value", e.admit_source)) == "born" and e.discharge_datetime:
                birth_discharge[r.patient.patient_id] = _day(e.discharge_datetime)
    assert birth_discharge, "the cohort must contain births"
    later = [
        e
        for r in dataset.patients
        if r.patient.patient_id in birth_discharge
        for e in r.encounters
        if _day(e.admission_datetime) > birth_discharge[r.patient.patient_id]
        and e.encounter_type.value == "outpatient"
        and "Vaccination visit" not in (e.chief_complaint or "")
    ]
    assert later, "newborns must receive calendar (well-child) visits after enrollment"


def test_no_encounter_starts_after_death(dataset) -> None:
    death = {}
    for r in dataset.patients:
        dod = r.patient.date_of_death
        if dod is not None:
            pid = r.patient.patient_id
            death[pid] = min(_day(dod), death.get(pid, _day(dod)))
    late = [
        (r.patient.patient_id, e.encounter_id)
        for r in dataset.patients
        if r.patient.patient_id in death
        for e in r.encounters
        if _day(e.admission_datetime) > death[r.patient.patient_id]
    ]
    assert late == []
