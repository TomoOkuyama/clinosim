"""Issue #3332: a vasopressor starts from the recorded mean arterial pressure
(low despite fluids), not on a fixed archetype day."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.simulator.vasopressor_initiation import (
    add_on_vasopressor_indicated,
    first_line_vasopressor,
    is_vasopressor_start,
    vasopressor_start_time,
)
from clinosim.types.encounter import Order, OrderStatus, OrderType, VitalSignRecord

pytestmark = pytest.mark.unit

_DAY = datetime(2025, 3, 1)


def _bp(hour: float, sbp: int, dbp: int) -> VitalSignRecord:
    return VitalSignRecord(timestamp=_DAY + timedelta(hours=hour), systolic_bp=sbp, diastolic_bp=dbp)


def _order(name: str, drug_id: str, hour: float, status: OrderStatus = OrderStatus.PLACED) -> Order:
    return Order(
        order_id=f"O-{drug_id}",
        patient_id="P",
        order_type=OrderType.MEDICATION,
        display_name=name,
        drug_id=drug_id,
        ordered_datetime=_DAY + timedelta(hours=hour),
        status=status,
    )


_FLUID = _order("IV_fluid: Lactated Ringer 30 mL/kg bolus", "lactated_ringer_solution", 1)
_NE = _order("Norepinephrine 0.1 ug/kg/min IV drip", "norepinephrine", 12)
# MAP 50 (80/35) and MAP 90 (130/70).
_LOW, _OK = (80, 35), (130, 70)


def test_two_low_readings_after_fluids_start_a_vasopressor_after_the_second() -> None:
    vitals = [_bp(6, *_OK), _bp(8, *_LOW), _bp(12, *_LOW), _bp(16, *_LOW)]
    start = vasopressor_start_time([_FLUID], vitals, _DAY)
    assert start == _DAY + timedelta(hours=12, minutes=30)


def test_a_normotensive_day_never_starts_one() -> None:
    assert vasopressor_start_time([_FLUID], [_bp(h, *_OK) for h in (2, 8, 14, 20)], _DAY) is None


def test_a_single_low_reading_is_not_persisting_hypotension() -> None:
    assert vasopressor_start_time([_FLUID], [_bp(8, *_LOW), _bp(12, *_OK), _bp(16, *_OK)], _DAY) is None


def test_readings_inside_the_fluid_window_do_not_count() -> None:
    # The bolus is ordered at 01:00; the window ends at 04:00.
    assert vasopressor_start_time([_FLUID], [_bp(2, *_LOW), _bp(3, *_LOW), _bp(6, *_OK)], _DAY) is None


def test_no_fluid_order_means_no_waiting() -> None:
    assert vasopressor_start_time([], [_bp(2, *_LOW), _bp(3, *_LOW)], _DAY) is not None


def test_a_running_vasopressor_is_not_started_again() -> None:
    assert vasopressor_start_time([_FLUID, _NE], [_bp(14, *_LOW), _bp(16, *_LOW)], _DAY) is None


def test_a_stopped_vasopressor_does_not_block_a_new_start() -> None:
    stopped = _order("Norepinephrine 0.1 ug/kg/min IV drip", "norepinephrine", 0, OrderStatus.STOPPED)
    assert vasopressor_start_time([_FLUID, stopped], [_bp(14, *_LOW), _bp(16, *_LOW)], _DAY) is not None


def test_the_order_stays_within_the_day() -> None:
    start = vasopressor_start_time([], [_bp(23, *_LOW), _bp(23.75, *_LOW)], _DAY)
    assert start is not None and start.date() == _DAY.date()


def test_a_second_vasopressor_needs_a_running_one_and_a_low_pressure_after_its_start() -> None:
    at = _DAY + timedelta(days=1, hours=10)
    assert not add_on_vasopressor_indicated([], [_bp(14, *_LOW)], at)
    assert not add_on_vasopressor_indicated([_NE], [_bp(8, *_LOW), _bp(14, *_OK)], at)
    assert add_on_vasopressor_indicated([_NE], [_bp(14, *_LOW)], at)


def test_vasopressor_start_entries_are_infusions_of_vasopressor_class_only() -> None:
    assert is_vasopressor_start({"drug_id": "norepinephrine", "dose": "0.1 ug/kg/min IV drip"})
    assert is_vasopressor_start({"drug_id": "vasopressin", "dose": "0.03 units/min IV continuous"})
    assert not is_vasopressor_start({"drug_id": "hydrocortisone", "dose": "50mg IV q6h"})
    assert not is_vasopressor_start({"drug_id": "dobutamine", "dose": "2-20ug/kg/min IV drip"})
    assert not is_vasopressor_start({"drug_id": "midodrine", "dose": "10mg PO TID"})


@pytest.mark.parametrize("disease", ["sepsis", "acute_mi", "pulmonary_embolism", "urinary_tract_infection"])
def test_the_first_line_vasopressor_is_norepinephrine(disease: str) -> None:
    entry = first_line_vasopressor(load_disease_protocol(disease), "smooth_recovery", "us")
    assert entry is not None and entry["drug_id"] == "norepinephrine"


def test_a_protocol_without_a_vasopressor_indicates_none() -> None:
    protocol = load_disease_protocol("sepsis")
    bare = protocol.model_copy(update={"drugs": {}, "course_archetypes": {}})
    assert first_line_vasopressor(bare, "smooth_recovery", "us") is None


@pytest.mark.parametrize("country", ["US", "JP"])
def test_forced_sepsis_stays_start_a_vasopressor_only_after_a_low_pressure(country: str) -> None:
    from clinosim.simulator import run_forced
    from clinosim.simulator.vasoactive_support import mean_arterial_pressure
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    logging.disable(logging.WARNING)
    try:
        ds = run_forced(
            ForcedScenario(disease_id="sepsis", count=6, severity="severe", archetype="sudden_deterioration"),
            SimulatorConfig(random_seed=23, country=country),
        )
    finally:
        logging.disable(logging.NOTSET)
    started = 0
    for record in ds.patients:
        starts = [o for o in record.orders if o.drug_id == "norepinephrine"]
        low = [
            v.timestamp
            for v in record.vital_signs
            if v.systolic_bp is not None and mean_arterial_pressure(v.systolic_bp, v.diastolic_bp) < 65
        ]
        for order in starts:
            started += 1
            assert any(ts < order.ordered_datetime for ts in low), "norepinephrine without a prior MAP < 65"
        # The existing rule: no discharge before the infusion was weaned off.
        discharge = record.encounters[0].discharge_datetime
        for order in starts:
            if order.end_datetime is not None and discharge is not None:
                assert discharge >= order.end_datetime
        if starts:
            first = min(o.ordered_datetime for o in starts)
            assert len([ts for ts in low if ts < first]) >= 2
    if country == "US":
        assert started, "no forced sudden-deterioration sepsis stay started a vasopressor"
    # The JP stays of this seed stay normotensive: none starts one.


def test_no_vasopressor_dose_is_charted_after_the_death() -> None:
    """A vasopressor started for the terminal hypotension charts the doses of
    the rest of the hospital day; those after the death time are not given."""
    from clinosim.simulator import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    logging.disable(logging.WARNING)
    try:
        ds = run_forced(
            ForcedScenario(disease_id="sepsis", count=6, severity="severe", archetype="sudden_deterioration"),
            SimulatorConfig(random_seed=23, country="JP"),
        )
    finally:
        logging.disable(logging.NOTSET)
    deaths = 0
    for record in ds.patients:
        enc = record.encounters[0]
        if enc.discharge_disposition != "exp" or enc.discharge_datetime is None:
            continue
        deaths += 1
        for mar in record.medication_administrations:
            when = mar.actual_datetime or mar.scheduled_datetime
            assert when <= enc.discharge_datetime, (
                f"{mar.drug_id} charted at {when} after death {enc.discharge_datetime}"
            )
    assert deaths
