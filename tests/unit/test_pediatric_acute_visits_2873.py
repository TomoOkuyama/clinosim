"""Issue #2873: a pediatric acute clinic visit carries its diagnosis, its
findings and its treatment; Z00 stays for well-child visits."""

from __future__ import annotations

import copy
from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.codes import code_exists, display, system_key_for
from clinosim.locale.loader import map_diagnosis_code
from clinosim.modules.pediatric.calendar import _YAML_PATH, load_pediatric_schedule, pediatric_presentation
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.encounter import ACUTE_COURSE
from clinosim.types.patient import BaselineVitals, PatientProfile

pytestmark = pytest.mark.unit

# visit id -> (US code, JP code, measured vitals, prescribed drug)
_ACUTE = {
    "pediatric_uri": ("J06.9", "J06.9", {"temp", "hr", "rr", "spo2"}, None),
    "pediatric_otitis_media": ("H66.90", "H66.9", {"temp", "hr", "rr", "spo2"}, "Amoxicillin"),
    "pediatric_bronchiolitis": ("J21.9", "J21.9", {"temp", "hr", "rr", "spo2"}, None),
    "pediatric_injury": ("T14.90", "T14.9", {"temp", "hr", "bp"}, None),
}
_FIELDS = {
    "temp": "temperature_celsius",
    "hr": "heart_rate",
    "bp": "systolic_bp",
    "rr": "respiratory_rate",
    "spo2": "spo2",
}


def _child(pid: str = "pt-child", dob: date = date(2024, 5, 1)) -> PatientProfile:
    p = PatientProfile(patient_id=pid)
    p.age = 1
    p.sex = "F"
    p.date_of_birth = dob
    p.baseline_vitals = BaselineVitals(temperature=36.6, heart_rate=110, respiratory_rate=26, spo2=98.5)
    return p


def _visit(visit: str, patient: PatientProfile | None = None, when: datetime = datetime(2025, 11, 3, 10, 5), seed=0):
    return _simulate_outpatient_visit(
        patient or _child(),
        "pediatric_visit",
        when,
        StaffRoster(),
        np.random.default_rng(seed),
        chronic_code=visit,
        followup_spec={"labs": []},
        country="US",
        department_id="pediatrics",
    )


def test_every_acute_visit_of_the_schedule_has_a_presentation() -> None:
    acute_ids = {e["disease_id"] for e in load_pediatric_schedule().values() if e["disease_id"] in _ACUTE}
    assert acute_ids == set(_ACUTE)
    for visit in _ACUTE:
        assert pediatric_presentation(visit) is not None, visit
    for visit in ("well_child_infant", "immunization_infant", "pediatric_behavioural"):
        assert pediatric_presentation(visit) is None, visit


@pytest.mark.parametrize("visit", sorted(_ACUTE))
def test_acute_visit_is_coded_with_its_illness_in_both_locales(visit: str) -> None:
    us_code, jp_code, _, _ = _ACUTE[visit]
    rec = _visit(visit)
    assert rec.clinical_diagnosis.admission_diagnosis_code == us_code
    assert rec.condition_event.ground_truth_diseases == [us_code]
    us = map_diagnosis_code(us_code, "US")
    jp = map_diagnosis_code(us_code, "JP")
    assert jp == jp_code
    assert code_exists(system_key_for("diagnosis", "US"), us, exact=True)
    assert code_exists(system_key_for("diagnosis", "JP"), jp, exact=True)
    assert display(system_key_for("diagnosis", "JP"), jp, "ja")


@pytest.mark.parametrize("visit", sorted(_ACUTE))
def test_acute_visit_emits_an_encounter_diagnosis_condition(visit: str) -> None:
    from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions

    us_code = _ACUTE[visit][0]
    record = {
        "patient": {"sex": "F", "chronic_conditions": []},
        "encounters": [
            {
                "encounter_id": "ENC-1",
                "encounter_type": "outpatient",
                "admission_datetime": "2025-11-03T10:05:00",
                "discharge_datetime": "2025-11-03T10:30:00",
            }
        ],
        "clinical_diagnosis": {"admission_diagnosis_code": us_code, "discharge_diagnosis_code": us_code},
    }
    conditions = _build_conditions(record, "pt-child", "US")
    categories = [c["category"][0]["coding"][0]["code"] for c in conditions]
    assert categories == ["encounter-diagnosis"]
    assert conditions[0]["code"]["coding"][0]["code"] == map_diagnosis_code(us_code, "US")


@pytest.mark.parametrize("visit", sorted(_ACUTE))
def test_acute_visit_measures_its_vital_set(visit: str) -> None:
    vital = _visit(visit).vital_signs[0]
    measured = {f for f, attr in _FIELDS.items() if getattr(vital, attr) is not None}
    assert measured == _ACUTE[visit][2]


@pytest.mark.parametrize("visit", ["pediatric_uri", "pediatric_otitis_media", "pediatric_bronchiolitis"])
def test_febrile_share_and_fever_follow_the_presentation(visit: str) -> None:
    presentation = pediatric_presentation(visit)
    assert presentation is not None
    febrile_temps, afebrile_temps = [], []
    for i in range(200):
        rec = _visit(visit, _child(pid=f"pt-{i}"), seed=i)
        state = presentation.visit_state(rec.encounters[0].encounter_id)
        (febrile_temps if state == "febrile" else afebrile_temps).append(rec.vital_signs[0].temperature_celsius)
    share = len(febrile_temps) / 200
    assert abs(share - presentation.febrile_probability) < 0.1
    assert np.mean(febrile_temps) >= 38.3
    assert sum(t >= 38.0 for t in febrile_temps) / len(febrile_temps) > 0.75
    assert np.mean(afebrile_temps) < 37.5


def test_injury_is_afebrile_with_a_pain_score() -> None:
    vital = _visit("pediatric_injury", _child(dob=date(2016, 5, 1))).vital_signs[0]
    assert vital.temperature_celsius < 38.0
    assert vital.pain_score == 3


@pytest.mark.parametrize(("dob", "days"), [(date(2024, 5, 1), 10), (date(2022, 5, 1), 7)])
def test_otitis_media_is_treated_with_amoxicillin_per_aap_2013(dob: date, days: int) -> None:
    rec = _visit("pediatric_otitis_media", _child(dob=dob))
    rx = rec.discharge_prescription
    assert rx is not None
    assert rx.issue_date == datetime(2025, 11, 3, 10, 5)
    assert len(rx.items) == 1
    item = rx.items[0]
    # 80-90 mg/kg/day in two divided doses; 10 days under 2 years, 7 days at 2-5 years.
    assert (item["drug_name"], item["drug_id"]) == ("Amoxicillin", "amoxicillin")
    assert item["drug_name_ja"] == "アモキシシリン"
    assert (item["dose"], item["route"], item["frequency"]) == ("45mg/kg", "PO", "BID")
    assert item["duration_days"] == days
    assert item["course"] == ACUTE_COURSE


@pytest.mark.parametrize("visit", ["pediatric_uri", "pediatric_bronchiolitis", "pediatric_injury"])
def test_supportive_care_visits_have_no_prescription(visit: str) -> None:
    assert _visit(visit).discharge_prescription is None


def test_well_child_visit_keeps_z00_and_its_vitals() -> None:
    rec = _visit("well_child_infant")
    assert rec.clinical_diagnosis.admission_diagnosis_code == "Z00"
    assert rec.discharge_prescription is None
    vital = rec.vital_signs[0]
    assert {f for f, attr in _FIELDS.items() if getattr(vital, attr) is not None} == {"temp", "hr"}


def test_an_acute_visit_draws_what_a_well_child_visit_draws() -> None:
    """The fever draw is stream-free: the visit's RNG ends where a
    well-child visit's does, so no later draw of the patient moves."""
    ends = []
    for visit in ("well_child_infant", "pediatric_uri", "pediatric_otitis_media", "pediatric_injury"):
        rng = np.random.default_rng(7)
        _simulate_outpatient_visit(
            _child(),
            "pediatric_visit",
            datetime(2025, 11, 3, 10, 5),
            StaffRoster(),
            rng,
            chronic_code=visit,
            country="US",
        )
        ends.append(rng.random())
    assert len(set(ends)) == 1


def test_fhir_marks_the_course_acute_and_never_a_renewal() -> None:
    from clinosim.modules.order.prescription_supersede import prescription_closures
    from clinosim.modules.output.fhir_r4.medications.medications import _build_discharge_medication_request

    def _rec(enc_id: str, issued: datetime):
        item = {"drug_name": "Amoxicillin", "dose": "45mg/kg", "frequency": "BID", "duration_days": 10}
        item["course"] = ACUTE_COURSE
        enc = SimpleNamespace(encounter_id=enc_id, encounter_type="outpatient")
        return SimpleNamespace(
            patient=SimpleNamespace(patient_id="P1", date_of_death=None),
            encounters=[enc],
            discharge_prescription=SimpleNamespace(issue_date=issued, items=[item]),
        )

    first, second = _rec("ENC-A", datetime(2025, 2, 1, 10)), _rec("ENC-B", datetime(2025, 6, 1, 10))
    closures = prescription_closures([first, second], date(2025, 12, 31))
    assert closures[("ENC-A", 1)] == {"status": "completed", "end_date": "2025-02-11"}
    assert closures[("ENC-B", 1)] == {"status": "completed", "end_date": "2025-06-11"}

    item = first.discharge_prescription.items[0]
    mr = _build_discharge_medication_request(item, "P1", "US", "ENC-A", "outpatient", 1, "2025-02-01T10:00:00Z")
    assert mr["courseOfTherapyType"]["coding"][0]["code"] == "acute"
    dose = mr["dosageInstruction"][0]["doseAndRate"][0]["doseQuantity"]
    assert (dose["value"], dose["code"]) == (45, "mg/kg")
    assert mr["dosageInstruction"][0]["timing"]["repeat"]["frequency"] == 2


def _schedule_with(tmp_path, presentation: dict):
    import yaml

    raw = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))
    raw = copy.deepcopy(raw)
    raw["presentations"] = {"pediatric_uri": presentation}
    p = tmp_path / "schedule.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return p


_OK = {
    "vitals": ["temp"],
    "febrile_probability": 0.5,
    "state_impact": {"febrile": {"inflammation_level": 0.7}},
    "pulmonary_involvement": False,
}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"vitals": ["temperature"]}, "vitals"),
        ({"febrile_probability": 1.5}, "febrile_probability"),
        ({"state_impact": {"afebrile": {"inflammation_level": 0.1}}}, "state_impact.febrile"),
        ({"state_impact": {"febrile": {"fever": 0.7}}}, "non-canonical"),
        (
            {"prescriptions": [{"drug_id": "no_such_drug", "dose": "1mg", "route": "PO", "frequency": "BID"}]},
            "drug catalog",
        ),
    ],
)
def test_load_time_validation_rejects_a_bad_presentation(tmp_path, change: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_pediatric_schedule(_schedule_with(tmp_path, {**_OK, **change}))


def test_load_time_validation_rejects_a_presentation_of_an_unscheduled_visit(tmp_path) -> None:
    import yaml

    p = _schedule_with(tmp_path, _OK)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["presentations"] = {"pediatric_flu": _OK}
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="unscheduled visits"):
        load_pediatric_schedule(p)
