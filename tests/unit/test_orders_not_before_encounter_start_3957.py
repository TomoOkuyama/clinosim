"""An order is never dated before the encounter it belongs to starts (Issue #3957).

ED lab, imaging and treatment order times are the arrival plus a normal draw,
and the admission work-up times are the admission plus a normal draw: a draw
below zero put the order (and the specimen, result and report that inherit its
time) a few minutes before the encounter. The draw is unchanged; the time is
held at the window start by :func:`clamp_to_window`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from clinosim import determinism
from clinosim.countries import lang_for
from clinosim.locale.i18n import t
from clinosim.locale.loader import load_demographics
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.healthcare_system.loader import load_healthcare_config
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import LifeEvent
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator import emergency
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.simulator.encounter_setup import clamp_to_window
from clinosim.simulator.enrichers import register_builtin_enrichers
from clinosim.simulator.inpatient import _simulate_patient
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import OrderType
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_START = datetime(2026, 3, 1, 21, 49)


# --- the helper ---------------------------------------------------------------


def test_a_time_before_the_start_is_held_at_the_start() -> None:
    assert clamp_to_window(_START - timedelta(minutes=5), _START) == _START


def test_a_time_inside_the_window_is_unchanged() -> None:
    inside = _START + timedelta(minutes=7)
    assert clamp_to_window(inside, _START) == inside
    assert clamp_to_window(_START, _START) == _START


def test_an_end_holds_a_late_time_and_no_end_leaves_it() -> None:
    end = _START + timedelta(hours=3)
    late = end + timedelta(minutes=1)
    assert clamp_to_window(late, _START, end) == end
    assert clamp_to_window(late, _START) == late


# --- ED visit -------------------------------------------------------------------


def _patient(seed: int, age: int):
    rng = determinism.default_rng(seed)
    person = PersonRecord(
        person_id=f"T-{seed}",
        household_id="H",
        age=age,
        sex="F",
        date_of_birth=date(2026 - age, 1, 1),
    )
    return activate_patient(person, rng, load_demographics("US"))


@pytest.mark.parametrize("condition", ["migraine", "abdominal_pain_nonspecific", "elderly_fall"])
def test_ed_orders_are_not_before_the_arrival_for_a_negative_draw(monkeypatch, condition: str) -> None:
    """A mean far below zero makes every offset draw negative: the lab, imaging
    and treatment orders of the visit must still be at or after the arrival."""
    for name in (
        "ED_LAB_ORDER_OFFSET_MEAN_MIN",
        "ED_IMAGING_ORDER_OFFSET_MEAN_MIN",
        "ED_TREATMENT_ORDER_OFFSET_MEAN_MIN",
    ):
        monkeypatch.setattr(emergency, name, -90.0)
    roster = generate_roster("medium", "US", determinism.default_rng(7))
    record = _simulate_ed_visit(
        _patient(3, 70),
        {"name": condition},
        _START,
        roster,
        determinism.default_rng(1003),
        country="US",
        force_severity="moderate",
    )
    orders = record.orders
    assert {OrderType.LAB, OrderType.IMAGING} & {o.order_type for o in orders}
    early = [(o.order_id, o.ordered_datetime) for o in orders if o.ordered_datetime < _START]
    assert early == []
    assert all(r.result_datetime >= _START for r in record.lab_results)


# --- admission work-up ------------------------------------------------------------


_EVENT_DATE = datetime(2026, 5, 24)


def _stay(disease: str):
    config = SimulatorConfig(random_seed=7, country="US")
    rng = determinism.default_rng(7)
    healthcare = load_healthcare_config("US")
    roster = generate_roster(config.hospital_scale, "US", rng)
    register_builtin_enrichers()
    person = PersonRecord(
        person_id="POP-T3957",
        household_id="HH-T3957",
        age=68,
        sex="M",
        date_of_birth=date(1958, 1, 1),
        family_name=t("module_text.test_family", lang_for("US")),
        given_name=t("module_text.test_given", lang_for("US"), n=1),
    )
    patient = activate_patient(person, rng, load_demographics("US"))
    event = LifeEvent(
        person_id=patient.patient_id,
        event_type="forced",
        timestamp=_EVENT_DATE,
        severity=0.5,
        disease_id=disease,
        requires_hospital=True,
        condition_type="known_disease",
    )
    return _simulate_patient(
        patient,
        event,
        disease,
        load_disease_protocol(disease),
        healthcare,
        roster,
        config,
        determinism.default_rng(11),
    )


@pytest.mark.parametrize("disease", ["elective_knee_arthroplasty", "bacterial_pneumonia"])
def test_admission_orders_are_not_before_the_encounter_start_for_a_negative_draw(monkeypatch, disease: str) -> None:
    """With every placement draw forced negative, no admission work-up order is
    dated before the start of its encounter: the admission for a direct
    admission, the ED arrival (the start of the ED phase, ``admission -
    admitted_ed_stay()``) for a stay admitted through the ED."""
    from clinosim.codes.hl7_encounter import AdmitSource
    from clinosim.modules.order import engine
    from clinosim.modules.triage.engine import admitted_ed_stay

    for name in (
        "ADMISSION_LAB_PLACEMENT_MEAN_MIN",
        "ADMISSION_IMAGING_PLACEMENT_MEAN_MIN",
        "ADMISSION_MED_PLACEMENT_MEAN_MIN",
        "ADMISSION_SUPPORTIVE_PLACEMENT_MEAN_MIN",
        "DAILY_IMAGING_PLACEMENT_MEAN_MIN",
    ):
        monkeypatch.setattr(engine, name, -600.0)
    record = _stay(disease)
    enc = record.encounters[0]
    via_ed = enc.admit_source == AdmitSource.EMD
    assert via_ed == (disease == "bacterial_pneumonia")
    floor = enc.admission_datetime - (admitted_ed_stay() if via_ed else timedelta(0))
    admission_work_up = [o for o in record.orders if "-ADM-" in o.order_id or o.order_id.split("-")[-1].startswith("I")]
    assert admission_work_up
    early = [(o.order_id, o.ordered_datetime) for o in admission_work_up if o.ordered_datetime < floor]
    assert early == []
    # the forced draw reaches the floor, so the rule (not the draw) holds the time
    assert any(o.ordered_datetime == floor for o in admission_work_up)
