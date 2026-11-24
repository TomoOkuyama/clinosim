"""Non-invasive ventilation when a complication requires it (Issue #3705)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.simulator import daily_loop as dl
from clinosim.simulator.oral_intake import npo_reason_at
from clinosim.simulator.oxygen_course import OxygenCourse, oxygen_course_rules
from clinosim.simulator.terminal_course import apply_terminal_course
from clinosim.simulator.vitals_pipeline import put_on_niv
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import OrderStatus, OrderType, VitalSignRecord

pytestmark = pytest.mark.unit

T0 = datetime(2026, 6, 14, 9, 0)
NIV = oxygen_course_rules().niv
VENT = oxygen_course_rules().ventilation


def _gain(r: float, f: float) -> float:
    return min(98.0, r + 1.5 * f)


def _reading(hour: float, spo2: float = 85.0, **kw) -> VitalSignRecord:
    return VitalSignRecord(timestamp=T0 + timedelta(hours=hour), heart_rate=100, systolic_bp=120, spo2=spo2, **kw)


def test_rules_come_from_yaml() -> None:
    assert NIV.device == "BiPAP" and NIV.start_action == "initiate_NIV_BiPAP" and NIV.max_days >= 1


def test_readings_on_niv_carry_the_device_and_a_raised_spo2() -> None:
    c = OxygenCourse()
    c.start_niv(T0 + timedelta(hours=2))
    assert c.niv_at(T0 + timedelta(hours=1)) is False
    on, flow, device, spo2 = c.resolve(T0 + timedelta(hours=3), 84.0, 92.0, (False, None, ""), _gain)
    assert (on, flow, device) == (True, None, NIV.device)
    assert spo2 == _gain(84.0, NIV.equivalent_flow_lpm)


def test_weaning_rule_does_not_remove_niv() -> None:
    c = OxygenCourse()
    c.start_niv(T0)
    for h in range(1, 60, 6):
        assert c.resolve(T0 + timedelta(hours=h), 99.0, 92.0, (False, None, ""), _gain)[2] == NIV.device


def test_niv_is_weaned_by_the_rule_and_oxygen_continues() -> None:
    c = OxygenCourse()
    c.start_niv(T0)
    assert c.niv_wean_due(NIV.oxygenation_impairment_below + 0.1, 0.0, 1, force=False) is False
    assert c.niv_wean_due(0.1, 0.1, 0, force=False) is False  # before the minimum days
    assert c.niv_wean_due(0.1, 0.1, NIV.min_days_after_start, force=False) is True
    c.end_niv(T0 + timedelta(days=2))
    assert c.niv_at(T0 + timedelta(days=2, hours=1)) is False
    assert (c.on, c.device, c.flow) == (True, NIV.post_niv_device, NIV.post_niv_flow_lpm)
    assert c.niv_during(T0 + timedelta(days=1)) is True and c.niv_during(T0 + timedelta(days=2)) is False


def test_niv_is_forced_off_after_max_days_and_at_the_end_of_the_stay() -> None:
    c = OxygenCourse()
    c.start_niv(T0)
    assert c.niv_wean_due(0.9, 0.9, NIV.max_days, force=False) is True
    assert OxygenCourse().niv_wean_due(0.9, 0.9, 1, force=True) is True


def test_intubation_during_niv_ends_niv_and_ventilates() -> None:
    c = OxygenCourse()
    c.start_niv(T0)
    c.start_ventilation(T0 + timedelta(hours=5))
    assert c.niv_at(T0 + timedelta(hours=6)) is False
    assert c.resolve(T0 + timedelta(hours=6), 80.0, 92.0, (False, None, ""), _gain)[2] == VENT.device
    c.start_niv(T0 + timedelta(hours=7))  # already ventilated: no effect
    assert c.niv_at(T0 + timedelta(hours=8)) is False


def test_put_on_niv_rewrites_only_later_readings() -> None:
    vitals = [_reading(1), _reading(5), _reading(6, on_supplemental_oxygen=True, oxygen_delivery_device="simple_mask")]
    put_on_niv(vitals, T0 + timedelta(hours=4), PhysiologicalState(), "copd_exacerbation")
    assert vitals[0].oxygen_delivery_device == ""
    for v in vitals[1:]:
        assert (v.on_supplemental_oxygen, v.oxygen_flow_rate_lpm, v.oxygen_delivery_device) == (True, None, NIV.device)
        assert v.spo2 is not None and v.spo2 >= 85.0


def test_npo_reason_while_on_niv() -> None:
    c = OxygenCourse()
    c.start_niv(T0)
    at = T0 + timedelta(hours=3)
    assert npo_reason_at([], at, c.ventilated_at) is None
    reason = npo_reason_at([], at, c.ventilated_at, niv_at=c.niv_at)
    assert reason and "non-invasive" in reason


def _stay_and_run(state: PhysiologicalState):
    stay = SimpleNamespace(
        patient=SimpleNamespace(patient_id="POP-1", age=78),
        encounter_id="ENC-1",
        admission_time=T0,
        attending_id="DR-1",
        disease_id="copd_exacerbation",
        country="JP",
    )
    return stay, dl._Run(state=state, differential=None, orders=[], dvt_prophylaxis_planned=False)


def test_start_niv_places_order_diet_and_rewrites_readings() -> None:
    stay, run = _stay_and_run(PhysiologicalState(oxygenation_impairment=0.6))
    run.prev_diet = "soft_diet"
    run.vitals = [_reading(2), _reading(30)]
    started = T0 + timedelta(days=1, hours=3)
    dl._start_niv(stay, run, 1, started)
    assert run.oxygen.niv_since == started
    assert run.vitals[0].oxygen_delivery_device == ""
    assert run.vitals[1].oxygen_delivery_device == NIV.device
    procs = [o for o in run.orders if o.order_type == OrderType.PROCEDURE]
    assert [o.display_name for o in procs] == [NIV.order_name] and procs[0].status == OrderStatus.PLACED
    assert [o.display_name for o in run.orders if o.order_type == OrderType.DIET] == [NIV.diet]
    # A second start while on NIV changes nothing.
    dl._start_niv(stay, run, 1, started + timedelta(hours=1))
    assert len([o for o in run.orders if o.order_type == OrderType.PROCEDURE]) == 1
    # Next day's diet stays NPO while on NIV even though inflammation is low.
    dl._order_diet(stay, run, 2)
    assert [o.display_name for o in run.orders if o.order_type == OrderType.DIET] == [NIV.diet]
    # Weaned at the start of the next day once the state recovered; the diet can advance after.
    run.state = PhysiologicalState()
    dl._update_niv(stay, run, 2, last_day=False)
    assert run.oxygen.niv_until == dl.hospital_day_start(T0, 3)


def test_complication_with_the_niv_action_starts_niv() -> None:
    stay, run = _stay_and_run(PhysiologicalState(oxygenation_impairment=0.6))
    stay.rng = np.random.default_rng(1)
    stay.severity = "moderate"
    stay.surgery = None
    stay.prior_procedures = []
    run.vitals = [_reading(30)]
    comp = {
        "name": "respiratory_failure_requiring_niv",
        "probability_per_day": 1.0,
        "onset_day_range": [0, 5],
        "state_impact": {"oxygenation_impairment": 0.1},
        "actions": [NIV.start_action, "continuous_monitoring"],
    }
    dl._apply_complications(stay, run, 1, [comp])
    assert [c["name"] for c in run.complications] == ["respiratory_failure_requiring_niv"]
    assert run.oxygen.niv_since is not None
    assert any(o.display_name == NIV.order_name for o in run.orders)


def test_final_readings_stay_on_niv_before_a_death() -> None:
    from tests.unit.simulator.test_mechanical_ventilation_3535 import DEATH, _patient

    oxygen = OxygenCourse()
    oxygen.start_niv(datetime(2026, 3, 4, 8, 0))
    vitals = [
        VitalSignRecord(
            timestamp=datetime(2026, 3, 4, h, 2),
            temperature_celsius=37.0,
            heart_rate=100,
            systolic_bp=110,
            diastolic_bp=70,
            respiratory_rate=20,
            spo2=90.0,
            measured_by="NS-1",
            on_supplemental_oxygen=True,
            oxygen_delivery_device=NIV.device,
        )
        for h in (6, 10, 14)
    ]
    apply_terminal_course(
        vitals,
        [PhysiologicalState(), PhysiologicalState()],
        _patient(),
        disease_id="copd_exacerbation",
        encounter_id="ENC-1",
        death_time=DEATH,
        stay_oxygen=oxygen,
    )
    window = [v for v in vitals if v.timestamp >= datetime(2026, 3, 4, 8, 0) and v.spo2 is not None]
    assert window and all(v.oxygen_delivery_device == NIV.device for v in window)


def test_complication_label_reads_as_a_diagnosis() -> None:
    from clinosim.modules.document.narrative.template_generator import _localize_complication

    assert _localize_complication("respiratory_failure_requiring_niv", "ja") == "非侵襲的陽圧換気を要する呼吸不全"
    assert "NPPV 適応" not in _localize_complication("respiratory_failure_requiring_niv", "ja")
    assert _localize_complication("respiratory_failure_requiring_niv", "en") == (
        "respiratory failure requiring non-invasive ventilation"
    )


def test_niv_device_record_spans_the_niv_readings() -> None:
    from clinosim.modules.device.engine import load_devices_config, place_devices_for_encounter
    from clinosim.types.encounter import Encounter, EncounterType
    from clinosim.types.output import CIFPatientRecord

    enc = Encounter(
        encounter_id="E-NIV",
        patient_id="P1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2026, 6, 13, 9, 0),
        discharge_datetime=datetime(2026, 6, 20, 9, 0),
    )

    def row(day: int, hour: int, device: str) -> VitalSignRecord:
        return VitalSignRecord(
            timestamp=datetime(2026, 6, day, hour),
            spo2=93.0,
            on_supplemental_oxygen=True,
            oxygen_delivery_device=device,
        )

    rec = CIFPatientRecord(
        patient=None,
        vital_signs=[
            row(14, 8, "simple_mask"),
            row(15, 12, NIV.device),
            row(16, 6, NIV.device),
            row(17, 8, "simple_mask"),
        ],
    )
    devices = [d for d in place_devices_for_encounter(rec, enc, load_devices_config()) if d.origin == "niv"]
    assert len(devices) == 1
    assert (devices[0].device_type, devices[0].snomed_code) == ("noninvasive_ventilator", "706226000")
    assert (devices[0].placement_date, devices[0].removal_date) == ("2026-06-15", "2026-06-17")
    # No reading on NIV: no device.
    none = CIFPatientRecord(patient=None, vital_signs=[row(14, 8, "simple_mask")])
    assert not [d for d in place_devices_for_encounter(none, enc, load_devices_config()) if d.origin == "niv"]


def test_an_oral_diet_ordered_later_the_same_day_is_cancelled() -> None:
    stay, run = _stay_and_run(PhysiologicalState(oxygenation_impairment=0.6))
    started = T0 + timedelta(days=1, hours=3)
    run.prev_diet = "NPO"
    dl._append_diet_order(stay, run, 1, "clear_liquid", started + timedelta(hours=9))
    assert run.prev_diet == "clear_liquid"
    dl._start_niv(stay, run, 1, started)
    diets = [(o.display_name, o.status) for o in run.orders if o.order_type == OrderType.DIET]
    assert (("clear_liquid", OrderStatus.CANCELLED)) in diets
    assert (NIV.diet, OrderStatus.PLACED) in diets
    assert run.prev_diet == NIV.diet


def test_a_protocol_niv_order_is_not_duplicated() -> None:
    from clinosim.types.encounter import Order

    stay, run = _stay_and_run(PhysiologicalState(oxygenation_impairment=0.6))
    run.orders.append(
        Order(
            order_id="ORD-PROTO",
            patient_id="POP-1",
            order_type=OrderType.PROCEDURE,
            display_name="NIV BiPAP (IPAP 12 / EPAP 5 cmH2O)",
            ordered_datetime=T0,
            status=OrderStatus.PLACED,
        )
    )
    dl._start_niv(stay, run, 1, T0 + timedelta(days=1, hours=3))
    assert [o.order_id for o in run.orders if o.order_type == OrderType.PROCEDURE] == ["ORD-PROTO"]
