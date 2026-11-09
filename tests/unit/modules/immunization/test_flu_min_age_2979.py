"""No influenza vaccine is given before 6 months of age (Issue #2979)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.immunization.engine import generate_immunizations, load_schedule
from clinosim.modules.immunization.enricher import _align_to_encounters
from clinosim.modules.immunization.visits import VaccinationVisit, bind_to_vaccination_visits, flu_season_months
from clinosim.modules.population.engine import PopulationRegistry, generate_healthcare_calendar
from clinosim.types.encounter import Encounter, EncounterType, ImmunizationRecord
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_SIX_MONTHS = 182


def _flu_cvx(country: str) -> set[str]:
    out: set[str] = set()
    for v in load_schedule(country).values():
        if v.get("frequency") == "annual":
            out |= {str(v["cvx"])} | {str(p["cvx"]) for p in v.get("products") or []}
    return out


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_flu_vaccine_is_licensed_from_six_months(country: str) -> None:
    annual = [v for v in load_schedule(country).values() if v.get("frequency") == "annual"]
    assert annual
    assert all(int(v["min_age_days"]) == _SIX_MONTHS for v in annual)


def test_engine_gives_no_flu_dose_before_six_months() -> None:
    """A baby born in June reaches 6 months on 2023-11-30: the 2023-24 season
    dose is never dated earlier, and it still falls in that season."""
    dob = date(2023, 6, 1)
    floor = dob + timedelta(days=_SIX_MONTHS)
    flu = _flu_cvx("US")
    first_season: list[date] = []
    for seed in range(300):
        baby = SimpleNamespace(patient_id=f"B{seed}", age=3, sex="F", date_of_birth=dob)
        recs = generate_immunizations(baby, load_schedule("US"), date(2026, 11, 1), np.random.default_rng(seed))
        days = [r.occurrence_date for r in recs if r.vaccine_cvx in flu]
        assert all(d >= floor for d in days), [d for d in days if d < floor]
        first_season += [d for d in days if d < date(2024, 6, 1)]
    assert first_season, "the season the baby turns 6 months still offers a dose"


def test_a_three_month_olds_flu_visit_gives_no_dose() -> None:
    dob = date(2023, 8, 15)
    baby = SimpleNamespace(patient_id="B1", age=3, sex="M", date_of_birth=dob, chronic_conditions=["X", "Y"])
    visit = VaccinationVisit(encounter_id="ENC-FLU", day=date(2023, 11, 15), is_flu=True)
    out = bind_to_vaccination_visits(
        [],
        [visit],
        baby,
        load_schedule("US"),
        as_of=date(2026, 11, 1),
        sim_start=date(2021, 11, 1),
        flu_visit_candidate=True,
        nurse="N1",
    )
    assert out == []


def test_a_flu_dose_is_not_aligned_onto_an_encounter_before_six_months() -> None:
    dob = date(2023, 8, 1)
    early = Encounter(
        encounter_id="ENC-4MO",
        encounter_type=EncounterType.OUTPATIENT,
        admission_datetime=datetime(2023, 12, 20, 9),
    )
    dose = ImmunizationRecord(vaccine_cvx="158", occurrence_date=date(2024, 2, 1))
    schedule = load_schedule("US")
    _align_to_encounters(
        [dose],
        [early],
        flu_season_months(schedule),
        earliest_by_cvx={c: dob + timedelta(days=_SIX_MONTHS) for c in _flu_cvx("US")},
    )
    assert dose.encounter_id == "" and dose.occurrence_date == date(2024, 2, 1)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_calendar_schedules_no_flu_visit_before_six_months(country: str) -> None:
    reg = PopulationRegistry()
    for i in range(400):
        p = PersonRecord(
            person_id=f"POP-{i:06d}",
            household_id="HH-000001",
            age=0,
            sex="M",
            date_of_birth=date(2025, 9, 1),
            chronic_conditions=["E11.9", "I10"],
        )
        reg.persons[p.person_id] = p
    events = generate_healthcare_calendar(reg, year=2025, country=country, rng=np.random.default_rng(7))
    assert not [e for e in events if e.disease_id == "flu_vaccination"]
