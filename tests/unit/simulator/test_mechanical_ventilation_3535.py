"""A stay is ventilated from the intubation until extubation or death (Issue #3535)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._vitals_line import PROGRESS_DAY, format_vitals_line
from clinosim.simulator import daily_loop as dl
from clinosim.simulator.oxygen_course import OxygenCourse, oxygen_course_rules
from clinosim.simulator.terminal_course import apply_terminal_course
from clinosim.simulator.vitals_pipeline import put_on_ventilator
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import OrderType, VitalSignRecord
from clinosim.types.patient import BaselineVitals, PatientProfile

pytestmark = pytest.mark.unit

T0 = datetime(2026, 3, 1, 9, 0)
VENT = oxygen_course_rules().ventilation


def _gain(r: float, f: float) -> float:
    return min(98.0, r + 1.5 * f)


def _reading(hour: float, spo2: float = 85.0, **kw) -> VitalSignRecord:
    return VitalSignRecord(
        timestamp=T0 + timedelta(hours=hour),
        heart_rate=100,
        systolic_bp=120,
        spo2=spo2,
        **kw,
    )


def test_ventilated_readings_carry_the_ventilator_device() -> None:
    c = OxygenCourse()
    c.start_ventilation(T0 + timedelta(hours=2))
    # Before the intubation the course is not ventilated.
    assert c.ventilated_at(T0 + timedelta(hours=1)) is False
    on, flow, device, spo2 = c.resolve(T0 + timedelta(hours=3), 84.0, 92.0, (False, None, ""), _gain)
    assert (on, flow, device) == (True, None, VENT.device)
    assert spo2 == _gain(84.0, VENT.equivalent_flow_lpm)


def test_weaning_rule_does_not_remove_the_ventilator() -> None:
    c = OxygenCourse()
    c.start_ventilation(T0)
    for h in range(1, 60, 6):
        assert c.resolve(T0 + timedelta(hours=h), 99.0, 92.0, (False, None, ""), _gain)[2] == VENT.device


def test_extubation_rule_and_post_extubation_oxygen() -> None:
    c = OxygenCourse()
    c.start_ventilation(T0)
    sick = (VENT.oxygenation_impairment_below + 0.1, 0.0)
    assert c.extubation_due(*sick, 1, force=False) is False
    assert c.extubation_due(0.1, 0.1, 0, force=False) is False  # before the minimum days
    ready_days = [c.extubation_due(0.1, 0.1, VENT.min_days_after_intubation, force=False) for _ in range(5)]
    assert ready_days[VENT.consecutive_days - 1 :] == [True] * (6 - VENT.consecutive_days)
    c.end_ventilation(T0 + timedelta(days=3))
    assert c.ventilated_at(T0 + timedelta(days=3, hours=1)) is False
    assert (c.on, c.device) == (True, VENT.post_extubation_device)
    assert c.ventilated_during(T0 + timedelta(days=2)) is True
    assert c.ventilated_during(T0 + timedelta(days=3)) is False


def test_extubation_forced_after_max_days_and_at_the_end() -> None:
    c = OxygenCourse()
    c.start_ventilation(T0)
    assert c.extubation_due(0.9, 0.9, VENT.max_days, force=False) is True
    assert OxygenCourse().extubation_due(0.9, 0.9, 1, force=True) is True


def test_put_on_ventilator_rewrites_only_later_readings() -> None:
    vitals = [_reading(1), _reading(5), _reading(6, on_supplemental_oxygen=True, oxygen_delivery_device="simple_mask")]
    put_on_ventilator(vitals, T0 + timedelta(hours=4), PhysiologicalState(), "")
    assert vitals[0].oxygen_delivery_device == ""
    for v in vitals[1:]:
        assert (v.on_supplemental_oxygen, v.oxygen_flow_rate_lpm, v.oxygen_delivery_device) == (True, None, VENT.device)
        assert v.spo2 is not None and v.spo2 >= 85.0


def _patient() -> PatientProfile:
    p = PatientProfile(patient_id="POP-1")
    p.age = 74
    p.sex = "M"
    p.date_of_birth = date(1951, 6, 1)
    p.baseline_vitals = BaselineVitals(
        temperature=36.6, heart_rate=76, systolic_bp=128, diastolic_bp=76, respiratory_rate=16, spo2=97.0
    )
    return p


DEATH = datetime(2026, 3, 5, 0, 35)


def _terminal(stay_oxygen: OxygenCourse | None, last_round_hour: int, **o2) -> list[VitalSignRecord]:
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
            **o2,
        )
        for h in (6, 10, 14, 18, 22)
        if h <= last_round_hour
    ]
    apply_terminal_course(
        vitals,
        [PhysiologicalState(), PhysiologicalState()],
        _patient(),
        disease_id="pneumonia",
        encounter_id="ENC-1",
        death_time=DEATH,
        stay_oxygen=stay_oxygen,
    )
    return vitals


def test_final_reading_keeps_the_oxygen_device() -> None:
    # The last round is hours before death: a final reading is appended; it
    # keeps the oxygen the patient was on instead of dropping it.
    vitals = _terminal(
        None, 14, on_supplemental_oxygen=True, oxygen_flow_rate_lpm=6.0, oxygen_delivery_device="simple_mask"
    )
    final = vitals[-1]
    assert final.timestamp > datetime(2026, 3, 4, 14, 2) and final.timestamp < DEATH
    assert final.on_supplemental_oxygen is True
    assert final.oxygen_delivery_device


def test_final_readings_stay_on_the_ventilator() -> None:
    oxygen = OxygenCourse()
    oxygen.start_ventilation(datetime(2026, 3, 4, 8, 0))
    vitals = _terminal(oxygen, 14, on_supplemental_oxygen=True, oxygen_delivery_device=VENT.device)
    window = [v for v in vitals if v.timestamp >= datetime(2026, 3, 4, 8, 0)]
    assert window and all(v.oxygen_delivery_device == VENT.device and v.on_supplemental_oxygen for v in window)
    assert vitals[-1].oxygen_delivery_device == VENT.device


def _stay_and_run(state: PhysiologicalState):
    stay = SimpleNamespace(
        patient=SimpleNamespace(patient_id="POP-1"),
        encounter_id="ENC-1",
        admission_time=T0,
        attending_id="DR-1",
        disease_id="pneumonia",
        country="US",
    )
    return stay, dl._Run(state=state, differential=None, orders=[], dvt_prophylaxis_planned=False)


def test_intubation_puts_the_stay_on_the_ventilator_with_an_npo_diet() -> None:
    severe = PhysiologicalState(oxygenation_impairment=0.9)
    stay, run = _stay_and_run(severe)
    run.prev_diet = "soft_diet"
    run.vitals = [_reading(2), _reading(h := 2 + dl.AIRWAY_ESCALATION_HOUR + 1)]
    dl._escalate_airway_and_icu(stay, run, 0)
    assert run.intubated and run.oxygen.ventilated_since is not None
    assert run.vitals[0].oxygen_delivery_device == ""
    assert run.vitals[1].oxygen_delivery_device == VENT.device and h
    diets = [o for o in run.orders if o.order_type == OrderType.DIET]
    assert [o.display_name for o in diets] == [VENT.diet]
    # Next day's diet order stays NPO while ventilated even though inflammation is low.
    dl._order_diet(stay, run, 1)
    assert [o.display_name for o in run.orders if o.order_type == OrderType.DIET] == [VENT.diet]
    # Extubation at the start of the next day once the state recovered.
    run.state = PhysiologicalState()
    dl._update_ventilation(stay, run, 1, last_day=False)
    assert run.oxygen.ventilated_until == dl.hospital_day_start(T0, 2)


def test_progress_vitals_line_does_not_say_room_air_on_the_ventilator() -> None:
    v = _reading(5, on_supplemental_oxygen=True, oxygen_delivery_device=VENT.device)
    line = format_vitals_line(v, PROGRESS_DAY, "en")
    assert "(RA)" not in line and "ventilat" in line.lower()
    assert "人工呼吸" in format_vitals_line(v, PROGRESS_DAY, "ja")


def test_shift_note_states_the_ventilation_not_room_air_or_no_oxygen() -> None:
    from clinosim.modules.document.narrative.renderers.nursing_shift_note import render_nursing_shift_note

    adm = "2026-08-31T09:54:00"
    readings = [
        {
            "timestamp": f"2026-08-31T{h:02d}:10:00",
            "heart_rate": 110,
            "systolic_bp": 100,
            "spo2": spo2,
            "on_supplemental_oxygen": True,
            "oxygen_delivery_device": VENT.device,
            "oxygen_flow_rate_lpm": None,
            "consciousness_level": "P",
        }
        for h, spo2 in ((12, 90.0), (15, 86.0))
    ]
    for lang, words in (("en", ("mechanical ventilation",)), ("ja", ("人工呼吸器",))):
        ctx = SimpleNamespace(
            target_lang=lang,
            locale="jp" if lang == "ja" else "us",
            authored_datetime=datetime(2026, 8, 31, 17, 0),
            day_index=0,
            shift="day",
            encounter={"encounter_id": "E1", "admission_datetime": adm, "primary_nurse_id": ""},
            roster_map={},
            vitals=readings,
            medications=[],
            nursing_risk_assessments=[],
            patient={"date_of_birth": "1950-01-01"},
            disease_protocol=None,
            author_practitioner_id="",
            intake_output_records=[],
            devices=[],
        )
        text = render_nursing_shift_note(ctx, SimpleNamespace()).raw_text
        assert all(w in text for w in words), text
        assert "(RA)" not in text and "酸素投与なし" not in text and "no oxygen given" not in text
        assert "supplemental O2" not in text and "酸素投与継続中" not in text


def test_ventilator_device_record_ends_at_the_extubation() -> None:
    from clinosim.simulator.device_removal import extubation_date

    def row(day: int, hour: int, device: str) -> SimpleNamespace:
        return SimpleNamespace(
            encounter_id="E1",
            timestamp=datetime(2026, 3, day, hour),
            spo2=95.0,
            oxygen_delivery_device=device,
        )

    enc = SimpleNamespace(encounter_id="E1")
    vent = VENT.device
    extubated = SimpleNamespace(vital_signs=[row(1, 10, vent), row(2, 10, vent), row(3, 8, "nasal_cannula")])
    assert extubation_date(extubated, enc) == date(2026, 3, 3)
    died_ventilated = SimpleNamespace(vital_signs=[row(1, 10, vent), row(2, 10, vent)])
    assert extubation_date(died_ventilated, enc) is None
    assert extubation_date(SimpleNamespace(vital_signs=[row(1, 10, "")]), enc) is None


def test_extubation_date_for_readings_without_an_encounter_id() -> None:
    from clinosim.simulator.device_removal import extubation_date

    def row(day: int, device: str) -> SimpleNamespace:
        return SimpleNamespace(timestamp=datetime(2026, 3, day, 10), spo2=95.0, oxygen_delivery_device=device)

    enc = SimpleNamespace(
        encounter_id="E1", admission_datetime=datetime(2026, 3, 1, 9), discharge_datetime=datetime(2026, 3, 9, 9)
    )
    rec = SimpleNamespace(vital_signs=[row(2, VENT.device), row(3, VENT.device), row(4, ""), row(20, VENT.device)])
    assert extubation_date(rec, enc) == date(2026, 3, 4)
