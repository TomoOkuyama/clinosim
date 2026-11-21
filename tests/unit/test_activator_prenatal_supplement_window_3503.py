"""Issue #3503 — prenatal supplements run only during a pregnancy and a
YAML-defined postpartum window, not for the rest of the simulation."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from clinosim.locale.loader import load_demographics, load_perinatal_config
from clinosim.modules.patient.activator import activate_patient
from clinosim.types.patient import HomeMedication, TemporalStatePeriod
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_DEMO = load_demographics("US")
_SUPPLEMENTS = {"folic acid", "ferrous fumarate"}


def _woman(periods: list[TemporalStatePeriod], meds: list[HomeMedication] | None = None) -> PersonRecord:
    p = PersonRecord(
        person_id="P-3503",
        household_id="H",
        sex="F",
        age=30,
        date_of_birth=date(1995, 1, 1),
        chronic_conditions=[],
    )
    p.state_periods = periods
    if meds:
        p.current_medications = meds
    return p


def _names(person: PersonRecord, year: int) -> set[str]:
    prof = activate_patient(person, np.random.default_rng(0), _DEMO, as_of_year=year)
    return {m.drug_name.lower() for m in prof.current_medications}


def _delivered(end: date) -> TemporalStatePeriod:
    return TemporalStatePeriod("pregnancy", end - timedelta(days=280), end, "delivered")


def _window_days() -> int:
    return int(load_perinatal_config()["lifecycle"]["prenatal_supplement_postpartum_days"])


def test_window_is_defined_in_yaml() -> None:
    assert _window_days() > 0


def test_supplements_during_pregnancy() -> None:
    open_preg = TemporalStatePeriod("pregnancy", date(2024, 3, 1), None)
    assert _names(_woman([open_preg]), 2024) & _SUPPLEMENTS


def test_supplements_absent_after_window() -> None:
    end = date(2020, 6, 1)
    assert end + timedelta(days=_window_days()) < date(2022, 1, 1)
    assert not (_names(_woman([_delivered(end)]), 2022) & _SUPPLEMENTS)


def test_carried_supplements_stop_after_window() -> None:
    meds = [HomeMedication(drug_name="Folic acid", dose="0.4mg", route="PO", frequency="daily")]
    assert not (_names(_woman([_delivered(date(2020, 6, 1))], meds), 2023) & _SUPPLEMENTS)


def test_supplements_in_postpartum_window() -> None:
    end = date(2024, 12, 20)
    assert _names(_woman([_delivered(end)]), 2024) & _SUPPLEMENTS


def test_iron_of_a_person_without_pregnancy_is_kept() -> None:
    meds = [HomeMedication(drug_name="Ferrous fumarate", dose="50mg", route="PO", frequency="daily")]
    assert "ferrous fumarate" in _names(_woman([], meds), 2023)
