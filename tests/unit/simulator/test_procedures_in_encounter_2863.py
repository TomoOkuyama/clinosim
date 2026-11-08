"""Issue #2863: procedures performed in an encounter lie inside its period."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import StaffRoster, generate_roster
from clinosim.simulator._ed_thresholds import ED_IMAGING_READ_MIN
from clinosim.simulator.ed_procedures import time_ed_procedures
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.simulator.encounter_setup import extend_visit_to_procedures, fit_procedures_in_stay
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.encounter import Encounter, Order, OrderType
from clinosim.types.patient import PatientProfile
from clinosim.types.procedure import ProcedureRecord

pytestmark = pytest.mark.unit

_T = datetime(2024, 6, 1, 14, 0)


def _proc(start: datetime, minutes: int, kind: str = "x", enc: str = "ENC-1") -> ProcedureRecord:
    return ProcedureRecord(
        encounter_id=enc,
        procedure_type=kind,
        start_datetime=start,
        end_datetime=start + timedelta(minutes=minutes),
        duration_minutes=minutes,
    )


def _inside(p: ProcedureRecord, start: datetime, end: datetime) -> bool:
    return start <= p.start_datetime <= p.end_datetime <= end


def test_a_late_procedure_is_moved_to_finish_at_the_end_of_the_stay() -> None:
    p = _proc(_T + timedelta(hours=9), 30)
    fit_procedures_in_stay([p], _T, _T + timedelta(hours=3))
    assert (p.start_datetime, p.end_datetime) == (_T + timedelta(hours=2, minutes=30), _T + timedelta(hours=3))
    assert p.duration_minutes == 30


def test_an_early_procedure_starts_with_the_stay() -> None:
    p = _proc(_T - timedelta(minutes=10), 20)
    fit_procedures_in_stay([p], _T, _T + timedelta(hours=1))
    assert (p.start_datetime, p.end_datetime) == (_T, _T + timedelta(minutes=20))


def test_a_procedure_longer_than_the_stay_is_shortened_to_it() -> None:
    p = _proc(_T + timedelta(minutes=5), 90)
    fit_procedures_in_stay([p], _T, _T + timedelta(minutes=40))
    assert (p.start_datetime, p.end_datetime, p.duration_minutes) == (_T, _T + timedelta(minutes=40), 40)


def test_a_stay_in_progress_bounds_only_the_start() -> None:
    p = _proc(_T + timedelta(days=3), 30)
    fit_procedures_in_stay([p], _T, None)
    assert p.start_datetime == _T + timedelta(days=3)


def test_a_visit_lasts_until_its_last_procedure_ends() -> None:
    enc = Encounter(encounter_id="ENC-1", admission_datetime=_T, discharge_datetime=_T + timedelta(minutes=15))
    other = _proc(_T, 600, enc="ENC-2")
    extend_visit_to_procedures(enc, [_proc(_T + timedelta(minutes=10), 60), _proc(_T, 20), other])
    assert enc.discharge_datetime == _T + timedelta(minutes=70)


def test_a_longer_visit_is_not_shortened() -> None:
    enc = Encounter(encounter_id="ENC-1", admission_datetime=_T, discharge_datetime=_T + timedelta(hours=1))
    extend_visit_to_procedures(enc, [_proc(_T, 15)])
    assert enc.discharge_datetime == _T + timedelta(hours=1)


def _order(kind: OrderType, minutes: int, route: str = "") -> Order:
    return Order(order_type=kind, route=route, ordered_datetime=_T + timedelta(minutes=minutes))


def test_ed_procedures_follow_the_visit_workflow() -> None:
    enc = Encounter(encounter_id="ENC-1", admission_datetime=_T, discharge_datetime=_T + timedelta(hours=4))
    later = _T + timedelta(hours=7)
    iv, reduction, splint = (
        _proc(later, 30, "iv_line"),
        _proc(later, 30, "reduction_closed"),
        _proc(later, 30, "short_arm_splint"),
    )
    orders = [_order(OrderType.IMAGING, 22), _order(OrderType.MEDICATION, 3, "IV")]
    time_ed_procedures([iv, reduction, splint], orders, enc)
    assert iv.start_datetime <= orders[1].ordered_datetime
    assert reduction.start_datetime == orders[0].ordered_datetime + timedelta(minutes=ED_IMAGING_READ_MIN)
    assert splint.start_datetime == reduction.end_datetime
    assert all(_inside(p, _T, _T + timedelta(hours=4)) for p in (iv, reduction, splint))


def test_ed_procedures_fit_a_short_stay() -> None:
    end = _T + timedelta(minutes=50)
    enc = Encounter(encounter_id="ENC-1", admission_datetime=_T, discharge_datetime=end)
    procs = [_proc(_T + timedelta(hours=5), 30, "wound_care"), _proc(_T + timedelta(hours=1), 25, "ecg_12lead")]
    time_ed_procedures(procs, [], enc)
    assert all(_inside(p, _T, end) for p in procs)


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("condition", ["wrist_fracture", "chest_pain_noncardiac"])
def test_simulated_ed_visits_keep_their_procedures_in_the_stay(condition: str, country: str) -> None:
    rng = determinism.default_rng(3)
    roster = generate_roster("medium", country, rng)
    seen = 0
    for i in range(12):
        person = PersonRecord(
            person_id=f"T-{i}", household_id="H-1", age=40, sex="M", date_of_birth=datetime(1984, 1, 1).date()
        )
        patient = activate_patient(person, rng, load_demographics(country))
        record = _simulate_ed_visit(
            patient, load_encounter_condition(condition), _T, roster, rng, country=country, force_severity="severe"
        )
        [enc] = record.encounters
        for p in record.procedures:
            seen += 1
            assert _inside(p, enc.admission_datetime, enc.discharge_datetime), (p.procedure_type, p, enc)
        imaging = [o.ordered_datetime for o in record.orders if o.order_type == OrderType.IMAGING]
        for p in record.procedures:
            if p.procedure_type == "reduction_closed" and imaging:
                assert p.start_datetime > max(imaging)
    assert seen


def test_a_chemo_visit_lasts_until_the_infusion_ends() -> None:
    spec = {
        "labs": [],
        "chemo_regimen": {"cycle_orders": [{"drug": "Leuprorelin", "dose": "3.75mg", "route": "SC"}]},
        "chemo_procedure": {"jp_code": "G004", "us_code": "96413", "duration_minutes": 60},
    }
    record = _simulate_outpatient_visit(
        patient=PatientProfile(patient_id="POP-000001", sex="M", age=68),
        visit_type="chemo_visit",
        visit_date=datetime(2024, 4, 15, 10, 0),
        roster=StaffRoster(),
        rng=determinism.default_rng(42),
        chronic_code="C61",
        followup_spec=spec,
        country="JP",
    )
    [enc] = record.encounters
    assert record.procedures
    assert all(_inside(p, enc.admission_datetime, enc.discharge_datetime) for p in record.procedures)
