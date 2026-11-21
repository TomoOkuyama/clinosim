"""Persistent reduced consciousness has a recorded cause (Issue #3519)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim import determinism
from clinosim.simulator.complications import normalized_complications
from clinosim.simulator.delirium import (
    delirium_code,
    delirium_rules,
    derive_delirium,
)
from clinosim.simulator.vitals_pipeline import _loc_for
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import VitalSignRecord

pytestmark = pytest.mark.unit

_ADM = datetime(2024, 6, 15, 8, 0)


def _vitals(levels: list[str]) -> list[VitalSignRecord]:
    """One AVPU assessment per hospital day."""
    return [
        VitalSignRecord(timestamp=_ADM + timedelta(days=d, hours=1), consciousness_level=lv)
        for d, lv in enumerate(levels)
    ]


def test_rules_load_and_name_f05() -> None:
    rules = delirium_rules()
    assert rules.icd_code == "F05"
    assert rules.complication_name == "delirium"
    assert delirium_code() == "F05"


def test_susceptible_patient_with_sustained_reduced_avpu_gets_delirium() -> None:
    ep = derive_delirium(_vitals(["A", "V", "V", "V", "A", "A"]), 0.45, _ADM)
    assert ep is not None
    assert ep["name"] == "delirium"
    assert ep["onset_day"] == 1
    assert ep["onset_datetime"].startswith("2024-06-16")
    assert ep["resolution_day"] == 4
    assert ep["duration_days"] == 3
    assert ep["source"] == "derived_from_consciousness"


def test_episode_still_present_at_the_end_of_the_stay_has_no_resolution() -> None:
    ep = derive_delirium(_vitals(["A", "V", "P", "V"]), 0.45, _ADM)
    assert ep is not None
    assert ep["resolution_day"] is None
    assert ep["duration_days"] == 3


def test_low_susceptibility_records_nothing() -> None:
    assert derive_delirium(_vitals(["A", "V", "V", "V"]), 0.05, _ADM) is None


def test_single_reduced_day_records_nothing() -> None:
    assert derive_delirium(_vitals(["A", "V", "A", "V", "A"]), 0.9, _ADM) is None


def test_unresponsive_days_are_not_delirium() -> None:
    assert derive_delirium(_vitals(["A", "U", "U", "U"]), 0.9, _ADM) is None


def test_existing_delirium_complication_is_not_duplicated() -> None:
    assert derive_delirium(_vitals(["V", "V", "V"]), 0.9, _ADM, existing=["icu_delirium"]) is None
    assert "icu_delirium" in delirium_rules().existing_names


def test_entry_round_trips_resolution_fields() -> None:
    ep = derive_delirium(_vitals(["V", "V", "A"]), 0.9, _ADM)
    assert ep is not None
    (norm,) = normalized_complications([ep])
    assert norm["resolution_day"] == 2 and norm["duration_days"] == 2


def _state(perfusion: float) -> PhysiologicalState:
    return PhysiologicalState(perfusion_status=perfusion)


def test_compensated_low_perfusion_is_not_a_multi_day_reduced_level() -> None:
    """The perfusion fallback reads a stable plateau at 0.35 as drowsiness every
    day; beyond the acute window it must give Alert (Issue #3519)."""
    assert all(_loc_for(_state(0.35), "acute_mi", 1, determinism.default_rng(s)) == "A" for s in range(20))


def test_acute_low_perfusion_still_reduces_the_level() -> None:
    assert {_loc_for(_state(0.35), "acute_mi", 0, determinism.default_rng(s)) for s in range(40)} <= {"V", "P"}


def test_refractory_shock_stays_reduced_on_any_day() -> None:
    assert _loc_for(_state(0.1), "sepsis", 6, determinism.default_rng(1)) in {"P", "U"}


@pytest.mark.parametrize("perfusion", [0.1, 0.35, 0.5, 0.9])
def test_the_rng_stream_is_consumed_identically_on_every_day(perfusion: float) -> None:
    a, b = determinism.default_rng(7), determinism.default_rng(7)
    _loc_for(_state(perfusion), "cerebral_infarction", 0, a)
    _loc_for(_state(perfusion), "cerebral_infarction", 9, b)
    assert a.random() == b.random()
