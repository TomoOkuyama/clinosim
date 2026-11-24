"""Issue #3270: a vasopressor / inotrope infusion is weaned off once the mean
arterial pressure and perfusion targets are met, and a patient is not
discharged while on vasoactive support or within the observation day off it."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.simulator.discharge_gate import (
    _check_discharge_ready,
    discharge_disposition_for,
    extend_stay_for_symptoms,
    unsafe_for_home,
)
from clinosim.simulator.medication_pipeline import _generate_mar
from clinosim.simulator.vasoactive_support import (
    hospital_day_start,
    mean_arterial_pressure,
    stop_weaned_vasoactive_infusions,
    vasoactive_support_after,
    vasoactive_weaning_rules,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import MedicationAdministration, Order, OrderStatus, OrderType, VitalSignRecord
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2026, 3, 1, 14, 0)
_NE_START = datetime(2026, 3, 2, 10, 0)


class _StubRoster:
    members: list = []

    def get_by_role(self, role: str, department: str | None = None) -> list:
        return []


def _order(order_id: str, drug: str, *, at: datetime = _NE_START, route: str = "IV") -> Order:
    return Order(
        order_id=order_id,
        encounter_id="ENC-3270",
        patient_id="POP-3270",
        order_type=OrderType.MEDICATION,
        display_name=drug,
        ordered_datetime=at,
        status=OrderStatus.PLACED,
        route=route,
    )


def _norepinephrine(at: datetime = _NE_START) -> Order:
    return _order("ORD-NE", "Norepinephrine 0.1ug/kg/min IV drip", at=at)


def _given(order: Order, at: datetime) -> MedicationAdministration:
    return MedicationAdministration(
        order_id=order.order_id, drug_name=order.display_name, scheduled_datetime=at, actual_datetime=at, status="given"
    )


def _bp_readings(start: datetime, end: datetime, sbp: int, dbp: int) -> list[VitalSignRecord]:
    out, t = [], start
    while t < end:
        out.append(VitalSignRecord(timestamp=t, systolic_bp=sbp, diastolic_bp=dbp, heart_rate=80))
        t += timedelta(hours=4)
    return out


def test_rules_load_with_the_ssc_map_target() -> None:
    rules = vasoactive_weaning_rules()
    assert rules.map_target_mmhg == 65
    assert rules.stable_hours > 0
    assert rules.off_support_days_before_discharge >= 1


def test_mean_arterial_pressure() -> None:
    assert mean_arterial_pressure(120, 60) == pytest.approx(80.0)


def test_hospital_day_start_is_midnight_of_the_calendar_day() -> None:
    assert hospital_day_start(_ADMIT, 0) == datetime(2026, 3, 1)
    assert hospital_day_start(_ADMIT, 3) == datetime(2026, 3, 4)


def test_norepinephrine_stops_after_a_day_at_target_pressure() -> None:
    ne = _norepinephrine()
    at = hospital_day_start(_ADMIT, 3)  # 2026-03-04 00:00, NE running since 03-02 10:00
    vitals = _bp_readings(at - timedelta(hours=24), at, 128, 74)
    stopped = stop_weaned_vasoactive_infusions([ne], [_given(ne, _NE_START)], vitals, False, at)
    assert stopped == [ne]
    assert ne.status == OrderStatus.STOPPED
    assert ne.end_datetime == at


def test_no_dose_is_given_after_the_stop() -> None:
    ne = _norepinephrine()
    at = hospital_day_start(_ADMIT, 3)
    stop_weaned_vasoactive_infusions(
        [ne], [_given(ne, _NE_START)], _bp_readings(at - timedelta(hours=24), at, 128, 74), False, at
    )
    mars = _generate_mar(
        PatientProfile(patient_id="POP-3270"),
        [ne],
        3,
        _ADMIT,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=np.random.default_rng(0),
    )
    assert [m for m in mars if m.order_id == "ORD-NE"] == []


def test_infusion_continues_while_map_is_below_target() -> None:
    ne = _norepinephrine()
    at = hospital_day_start(_ADMIT, 3)
    vitals = _bp_readings(at - timedelta(hours=24), at, 128, 74)
    vitals.append(VitalSignRecord(timestamp=at - timedelta(hours=2), systolic_bp=84, diastolic_bp=50))  # MAP 61
    assert stop_weaned_vasoactive_infusions([ne], [_given(ne, _NE_START)], vitals, False, at) == []
    assert ne.status == OrderStatus.PLACED


def test_infusion_continues_while_in_shock() -> None:
    ne = _norepinephrine()
    at = hospital_day_start(_ADMIT, 3)
    vitals = _bp_readings(at - timedelta(hours=24), at, 128, 74)
    assert stop_weaned_vasoactive_infusions([ne], [_given(ne, _NE_START)], vitals, True, at) == []


def test_infusion_started_inside_the_window_is_not_weaned_yet() -> None:
    at = hospital_day_start(_ADMIT, 2)  # 03-03 00:00; NE started 03-02 10:00 (< 24 h)
    ne = _norepinephrine()
    vitals = _bp_readings(at - timedelta(hours=24), at, 128, 74)
    assert stop_weaned_vasoactive_infusions([ne], [_given(ne, _NE_START)], vitals, False, at) == []


def test_a_reorder_of_a_running_drug_is_not_a_new_start() -> None:
    ne = _norepinephrine()
    again = _order("ORD-NE2", "Norepinephrine 0.05-0.3ug/kg/min IV drip", at=_NE_START + timedelta(days=1))
    at = hospital_day_start(_ADMIT, 3)
    vitals = _bp_readings(at - timedelta(hours=24), at, 128, 74)
    stopped = stop_weaned_vasoactive_infusions([ne, again], [_given(ne, _NE_START)], vitals, False, at)
    assert {o.order_id for o in stopped} == {"ORD-NE", "ORD-NE2"}


def test_a_new_vasoactive_drug_in_the_window_defers_the_wean() -> None:
    ne = _norepinephrine()
    dobu = _order("ORD-DOBU", "Dobutamine 5ug/kg/min IV drip", at=_NE_START + timedelta(days=1))
    at = hospital_day_start(_ADMIT, 3)
    vitals = _bp_readings(at - timedelta(hours=24), at, 128, 74)
    assert stop_weaned_vasoactive_infusions([ne, dobu], [_given(ne, _NE_START)], vitals, False, at) == []


def test_end_is_never_before_the_order_time() -> None:
    at = hospital_day_start(_ADMIT, 3)
    ne = _norepinephrine(at=at + timedelta(hours=1))  # dose charted on the day before the order time
    vitals = _bp_readings(at - timedelta(hours=24), at, 128, 74)
    stop_weaned_vasoactive_infusions([ne], [_given(ne, at - timedelta(hours=30))], vitals, False, at)
    assert ne.end_datetime == ne.ordered_datetime


def test_without_recorded_pressures_the_infusion_continues() -> None:
    ne = _norepinephrine()
    at = hospital_day_start(_ADMIT, 3)
    assert stop_weaned_vasoactive_infusions([ne], [_given(ne, _NE_START)], [], False, at) == []


def test_all_vasoactive_infusions_stop_together_and_other_drugs_are_untouched() -> None:
    ne = _norepinephrine()
    dobu = _order("ORD-DOBU", "Dobutamine 5ug/kg/min IV drip")
    abx = _order("ORD-ABX", "Meropenem 1g IV q8h")
    at = hospital_day_start(_ADMIT, 3)
    vitals = _bp_readings(at - timedelta(hours=24), at, 128, 74)
    mars = [_given(ne, _NE_START), _given(dobu, _NE_START), _given(abx, _NE_START)]
    stopped = stop_weaned_vasoactive_infusions([ne, dobu, abx], mars, vitals, False, at)
    assert {o.order_id for o in stopped} == {"ORD-NE", "ORD-DOBU"}
    assert abx.status == OrderStatus.PLACED


def test_a_one_time_epinephrine_dose_is_not_an_infusion() -> None:
    epi = _order("ORD-EPI", "Epinephrine 0.3mg IM", route="IM")
    epi.single_dose = True
    at = hospital_day_start(_ADMIT, 3)
    assert not vasoactive_support_after([epi], at - timedelta(days=2))


def test_support_after_cutoff_running_or_recently_stopped() -> None:
    ne = _norepinephrine()
    cutoff = hospital_day_start(_ADMIT, 4)
    assert vasoactive_support_after([ne], cutoff)  # still running
    ne.status, ne.end_datetime = OrderStatus.STOPPED, cutoff + timedelta(hours=1)
    assert vasoactive_support_after([ne], cutoff)
    ne.end_datetime = cutoff
    assert not vasoactive_support_after([ne], cutoff)


def test_check_discharge_ready_is_false_while_on_vasoactive_support() -> None:
    state = PhysiologicalState()
    assert _check_discharge_ready(state, 5, "us")
    assert not _check_discharge_ready(state, 5, "us", on_vasoactive_support=True)
    assert unsafe_for_home(state, {}, on_vasoactive_support=True)


def test_stay_extends_past_max_los_while_on_support_up_to_the_cap() -> None:
    state = PhysiologicalState()
    cap = vasoactive_weaning_rules().max_extension_days
    assert not extend_stay_for_symptoms(state, 8, 8)
    assert extend_stay_for_symptoms(state, 8, 8, on_vasoactive_support=True)
    assert not extend_stay_for_symptoms(state, 8 + cap, 8, on_vasoactive_support=True)


def test_disposition_is_not_home_on_vasoactive_support() -> None:
    state = PhysiologicalState()
    assert discharge_disposition_for(state, {}, died=False) == DischargeDisposition.HOME
    assert discharge_disposition_for(state, {}, died=False, on_vasoactive_support=True) != DischargeDisposition.HOME


def test_shock_physiology_is_one_definition_with_icu_escalation() -> None:
    from clinosim.simulator.daily_loop import icu_escalation_needed, in_shock

    shock = PhysiologicalState(perfusion_status=0.2)
    assert in_shock(shock) and icu_escalation_needed(shock)
    assert not in_shock(PhysiologicalState())


@pytest.fixture(scope="module")
def urosepsis_with_norepinephrine():
    from clinosim.simulator import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    scenario = ForcedScenario(
        disease_id="urinary_tract_infection", count=16, severity="severe", archetype="sudden_deterioration"
    )
    return run_forced(scenario, SimulatorConfig(random_seed=7, country="US"))


def test_simulated_stay_weans_norepinephrine_and_observes_before_discharge(urosepsis_with_norepinephrine) -> None:
    from clinosim.simulator.medication_pipeline import is_vasoactive_infusion

    checked = 0
    for record in urosepsis_with_norepinephrine.patients:
        enc = record.encounters[0]
        vaso = [o for o in record.orders if is_vasoactive_infusion(o)]
        if not vaso:  # Issue #3332: a vasopressor starts only from recorded hypotension.
            continue
        if enc.discharge_disposition == DischargeDisposition.EXP or enc.discharge_datetime is None:
            continue
        ids = {o.order_id for o in vaso}
        given_days = {
            (m.actual_datetime or m.scheduled_datetime).date()
            for m in record.medication_administrations
            if m.order_id in ids and m.status == "given"
        }
        last_two = {enc.discharge_datetime.date(), enc.discharge_datetime.date() - timedelta(days=1)}
        assert not given_days & last_two
        assert all(o.end_datetime is not None and o.end_datetime < enc.discharge_datetime for o in vaso)
        checked += 1
    assert checked
