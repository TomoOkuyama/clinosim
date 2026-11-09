"""A vaccination visit records the vaccine given at it (Issue #2868)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.immunization import enricher as enricher_mod
from clinosim.modules.immunization.enricher import _align_to_encounters, enrich_immunizations
from clinosim.modules.immunization.visits import (
    VaccinationVisit,
    flu_season_months,
    is_flu_visit_candidate,
    vaccination_visits_by_patient,
)
from clinosim.modules.immunization.visits import bind_to_vaccination_visits as _bind
from clinosim.modules.population import is_flu_vaccination_candidate
from clinosim.simulator._dispatch import InpatientStayIndex
from clinosim.types.encounter import Encounter, EncounterStatus, EncounterType, ImmunizationRecord
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_FLU = {
    "cvx": "150",
    "products": [{"cvx": "150", "until": "2024-06-30"}, {"cvx": "140", "from": "2024-07-01"}],
    "min_age": 18,
    "frequency": "annual",
    "available_from": "2000-01-01",
    "history_years": 10,
    "seasonal_distribution": {"9": 0.1, "10": 0.4, "11": 0.3, "12": 0.1, "1": 0.07, "2": 0.03},
    "coverage_by_age_sex": {"18-99": {"M": 1.0, "F": 1.0}},
}
_DTAP = {
    "cvx": "20",
    "min_age": 0,
    "frequency": "pediatric_series",
    "available_from": "2000-01-01",
    "doses": [
        {"dose_number": 4, "age_days_min": 455, "age_days_max": 545, "coverage_by_sex": {"M": 1.0, "F": 1.0}},
        {"dose_number": 5, "age_days_min": 1460, "age_days_max": 2190, "coverage_by_sex": {"M": 1.0, "F": 1.0}},
    ],
}
_MMR = {
    "cvx": "03",
    "min_age": 0,
    "frequency": "pediatric_series",
    "available_from": "2000-01-01",
    "doses": [
        {"dose_number": 1, "age_days_min": 365, "age_days_max": 455, "coverage_by_sex": {"M": 1.0, "F": 1.0}},
        {"dose_number": 2, "age_days_min": 1460, "age_days_max": 2190, "coverage_by_sex": {"M": 1.0, "F": 1.0}},
    ],
}


def _adult(age: int = 70, chronic: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        patient_id="P1",
        age=age,
        sex="F",
        date_of_birth=date(2024 - age, 3, 1),
        chronic_conditions=["X"] * chronic,
    )


def bind_to_vaccination_visits(imms, visits, patient, schedule, **kwargs):
    return _bind(imms, visits, patient, schedule, flu_visit_candidate=is_flu_visit_candidate(patient), **kwargs)


def _flu_visit(day: date, eid: str = "ENC-FLU") -> VaccinationVisit:
    return VaccinationVisit(encounter_id=eid, day=day, is_flu=True)


def test_flu_visit_gets_the_season_dose_redated_to_the_visit() -> None:
    engine_dose = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2024, 9, 1), administered_by="N1")
    out = bind_to_vaccination_visits(
        [engine_dose],
        [_flu_visit(date(2024, 11, 12))],
        _adult(),
        {"influenza": _FLU},
        as_of=date(2025, 12, 31),
        sim_start=date(2023, 1, 1),
    )
    assert len(out) == 1
    assert out[0].encounter_id == "ENC-FLU"
    assert out[0].occurrence_date == date(2024, 11, 12)
    assert out[0].administered_by == "N1"
    assert out[0].lot_number.startswith("L") and "-202411-" in out[0].lot_number


def test_flu_visit_without_an_engine_dose_records_a_new_one() -> None:
    out = bind_to_vaccination_visits(
        [],
        [_flu_visit(date(2023, 10, 20))],
        _adult(),
        {"influenza": _FLU},
        as_of=date(2025, 12, 31),
        sim_start=date(2023, 1, 1),
        nurse="N9",
    )
    assert [(r.vaccine_cvx, r.occurrence_date, r.encounter_id, r.status, r.administered_by) for r in out] == [
        ("150", date(2023, 10, 20), "ENC-FLU", "completed", "N9")
    ]


def test_no_second_dose_or_refusal_in_a_season_with_a_flu_visit() -> None:
    recs = [
        ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2024, 10, 1)),
        ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2025, 1, 1)),
        ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2024, 12, 1), status="not-done"),
    ]
    out = bind_to_vaccination_visits(
        recs,
        [_flu_visit(date(2024, 11, 5)), _flu_visit(date(2024, 12, 5), "ENC-FLU-2")],
        _adult(),
        {"influenza": _FLU},
        as_of=date(2025, 12, 31),
        sim_start=date(2023, 1, 1),
    )
    assert [(r.occurrence_date, r.status, r.encounter_id) for r in out] == [(date(2024, 11, 5), "completed", "ENC-FLU")]


def test_flu_visit_candidate_without_a_visit_gets_no_off_visit_dose() -> None:
    """The calendar's visit draw decides a candidate's season; the engine's
    own dose would double the calibrated coverage."""
    dose = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2024, 10, 1))
    kwargs = {"as_of": date(2025, 12, 31), "sim_start": date(2023, 1, 1)}
    assert bind_to_vaccination_visits([dose], [], _adult(70), {"influenza": _FLU}, **kwargs) == []
    # Not offered flu visits (under 65, under two chronic conditions): the engine decides.
    kept = bind_to_vaccination_visits([dose], [], _adult(40, chronic=1), {"influenza": _FLU}, **kwargs)
    assert kept == [dose]
    # A season the calendar did not cover (before the simulation): the engine decides.
    early = ImmunizationRecord(vaccine_cvx="150", occurrence_date=date(2021, 10, 1))
    assert bind_to_vaccination_visits([early], [], _adult(70), {"influenza": _FLU}, **kwargs) == [early]


def test_one_flu_record_per_season_prefers_the_dose() -> None:
    recs = [
        ImmunizationRecord(vaccine_cvx="150", occurrence_date=date(2021, 10, 1), status="not-done"),
        ImmunizationRecord(vaccine_cvx="150", occurrence_date=date(2021, 11, 1)),
    ]
    out = bind_to_vaccination_visits(
        recs, [], _adult(40), {"influenza": _FLU}, as_of=date(2025, 12, 31), sim_start=date(2023, 1, 1)
    )
    assert [(r.occurrence_date, r.status) for r in out] == [(date(2021, 11, 1), "completed")]


def test_kindergarten_visit_records_the_boosters_due_at_that_age() -> None:
    child = SimpleNamespace(patient_id="C1", age=5, sex="M", date_of_birth=date(2019, 2, 1), chronic_conditions=[])
    visit = VaccinationVisit(encounter_id="ENC-KG", day=date(2024, 6, 10), is_flu=False)  # 5y 4m
    recs = [
        ImmunizationRecord(vaccine_cvx="20", occurrence_date=date(2020, 5, 1), dose_number=4),
        ImmunizationRecord(vaccine_cvx="20", occurrence_date=date(2024, 2, 5), dose_number=5),
        ImmunizationRecord(vaccine_cvx="03", occurrence_date=date(2020, 2, 3), dose_number=1),
    ]
    out = bind_to_vaccination_visits(
        recs,
        [visit],
        child,
        {"dtap": _DTAP, "mmr": _MMR},
        as_of=date(2025, 12, 31),
        sim_start=date(2023, 1, 1),
    )
    at_visit = sorted((r.vaccine_cvx, r.dose_number) for r in out if r.encounter_id == "ENC-KG")
    # DTaP 5 moved to the visit, MMR 2 added (dose 1 was given).
    assert at_visit == [("03", 2), ("20", 5)]
    assert all(r.occurrence_date == date(2024, 6, 10) for r in out if r.encounter_id == "ENC-KG")
    assert len(out) == 4


def test_pediatric_visit_does_not_restart_a_discontinued_series() -> None:
    """No dose is given out of order; the visit documents the due dose as
    not done (Issue #2974), so a vaccination visit never records nothing."""
    child = SimpleNamespace(patient_id="C2", age=5, sex="M", date_of_birth=date(2019, 2, 1), chronic_conditions=[])
    visit = VaccinationVisit(encounter_id="ENC-KG", day=date(2024, 6, 10), is_flu=False)
    out = bind_to_vaccination_visits(
        [], [visit], child, {"mmr": _MMR}, as_of=date(2025, 12, 31), sim_start=date(2023, 1, 1)
    )
    assert [(r.vaccine_cvx, r.dose_number, r.status, r.encounter_id, r.occurrence_date) for r in out] == [
        ("03", 2, "not-done", "ENC-KG", date(2024, 6, 10))
    ]
    assert out[0].lot_number == ""


def test_an_unbound_refusal_of_the_due_dose_is_charted_at_the_visit_2974() -> None:
    child = SimpleNamespace(patient_id="C3", age=5, sex="M", date_of_birth=date(2019, 2, 1), chronic_conditions=[])
    visit = VaccinationVisit(encounter_id="ENC-KG", day=date(2024, 6, 10), is_flu=False)
    refusal = ImmunizationRecord(vaccine_cvx="03", occurrence_date=date(2023, 3, 1), status="not-done", dose_number=2)
    out = bind_to_vaccination_visits(
        [refusal], [visit], child, {"mmr": _MMR}, as_of=date(2025, 12, 31), sim_start=date(2023, 1, 1)
    )
    assert len(out) == 1
    assert (out[0].status, out[0].encounter_id, out[0].occurrence_date) == ("not-done", "ENC-KG", date(2024, 6, 10))


def test_a_dose_given_the_same_day_at_another_encounter_moves_to_the_visit_2974() -> None:
    """A dose charted on the vaccination visit's day at another encounter (a
    same-day well-child visit) is given at the vaccination visit."""
    child = SimpleNamespace(patient_id="C4", age=5, sex="M", date_of_birth=date(2019, 2, 1), chronic_conditions=[])
    visit = VaccinationVisit(encounter_id="ENC-KG", day=date(2024, 6, 10), is_flu=False)
    recs = [
        ImmunizationRecord(vaccine_cvx="03", occurrence_date=date(2020, 2, 3), dose_number=1),
        ImmunizationRecord(vaccine_cvx="03", occurrence_date=date(2024, 6, 10), dose_number=2, encounter_id="ENC-WELL"),
    ]
    out = bind_to_vaccination_visits(
        recs, [visit], child, {"mmr": _MMR}, as_of=date(2025, 12, 31), sim_start=date(2023, 1, 1)
    )
    assert [(r.dose_number, r.encounter_id, r.status) for r in out if r.occurrence_date == visit.day] == [
        (2, "ENC-KG", "completed")
    ]
    assert len(out) == 2


def test_a_dose_bound_to_another_vaccination_visit_stays_there_2974() -> None:
    child = SimpleNamespace(patient_id="C5", age=5, sex="M", date_of_birth=date(2019, 2, 1), chronic_conditions=[])
    first = VaccinationVisit(encounter_id="ENC-KG1", day=date(2024, 6, 10), is_flu=False)
    second = VaccinationVisit(encounter_id="ENC-KG2", day=date(2024, 6, 10), is_flu=False)
    recs = [ImmunizationRecord(vaccine_cvx="03", occurrence_date=date(2020, 2, 3), dose_number=1)]
    out = bind_to_vaccination_visits(
        recs, [first, second], child, {"mmr": _MMR}, as_of=date(2025, 12, 31), sim_start=date(2023, 1, 1)
    )
    assert [r.encounter_id for r in out if r.dose_number == 2 and r.status == "completed"] == ["ENC-KG1"]


def test_a_visit_gives_one_dose_of_a_series() -> None:
    """Overlapping dose windows (HPV 1 at 11-13 y, HPV 2 at 11.5-14 y) give
    the series' next dose only, not both on one day."""
    hpv = {
        "cvx": "165",
        "min_age": 0,
        "frequency": "pediatric_series",
        "available_from": "2015-01-01",
        "doses": [
            {"dose_number": 1, "age_days_min": 4015, "age_days_max": 4745, "coverage_by_sex": {"M": 1.0}},
            {"dose_number": 2, "age_days_min": 4195, "age_days_max": 5110, "coverage_by_sex": {"M": 1.0}},
        ],
    }
    teen = SimpleNamespace(patient_id="T1", age=12, sex="M", date_of_birth=date(2012, 1, 1), chronic_conditions=[])
    visit = VaccinationVisit(encounter_id="ENC-ADOL", day=date(2024, 6, 10), is_flu=False)  # 12y 5m
    out = bind_to_vaccination_visits(
        [], [visit], teen, {"hpv": hpv}, as_of=date(2025, 12, 31), sim_start=date(2023, 1, 1)
    )
    assert [(r.vaccine_cvx, r.dose_number) for r in out] == [("165", 1)]


def test_flu_dose_aligns_only_inside_its_season_months() -> None:
    enc = Encounter(
        encounter_id="ENC-JUL",
        encounter_type=EncounterType.OUTPATIENT,
        admission_datetime=datetime(2024, 7, 20, 9),
    )
    flu = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2024, 9, 1))
    other = ImmunizationRecord(vaccine_cvx="115", occurrence_date=date(2024, 9, 1))
    _align_to_encounters([flu, other], [enc], flu_season_months({"influenza": _FLU}))
    assert flu.encounter_id == "" and flu.occurrence_date == date(2024, 9, 1)
    assert other.encounter_id == "ENC-JUL"


def test_vaccination_visits_are_read_from_the_visit_reason() -> None:
    def _rec(eid: str, chief: str, dx: str):
        enc = Encounter(
            encounter_id=eid,
            encounter_type=EncounterType.OUTPATIENT,
            admission_datetime=datetime(2024, 11, 1, 9),
            chief_complaint=chief,
        )
        return SimpleNamespace(
            patient=SimpleNamespace(patient_id="P1"),
            encounters=[enc],
            clinical_diagnosis=SimpleNamespace(admission_diagnosis_code=dx),
        )

    visits = vaccination_visits_by_patient(
        [
            _rec("E-FLU", "Influenza vaccination", "Z23"),
            _rec("E-KG", "Immunization visit — kindergarten entry boosters", "Z23"),
            _rec("E-HTN", "Blood pressure management", "I10"),
            _rec("ENC-VAX-P1-abc", "Vaccination visit", "Z23"),
        ]
    )["P1"]
    assert [(v.encounter_id, v.is_flu) for v in visits] == [("E-FLU", True), ("E-KG", False)]


def test_flu_visit_rate_is_the_schedule_coverage_for_the_age() -> None:
    """The calendar's flu visit decides a candidate's season, so it fires at
    the calibrated per-season coverage for the age, chronic conditions or not."""
    from clinosim.modules.immunization.engine import load_schedule, seasonal_flu_coverage

    flu = load_schedule("US")["influenza"]
    assert seasonal_flu_coverage("US", 70, "F") == flu["coverage_by_age_sex"]["65-99"]["F"]
    assert seasonal_flu_coverage("US", 40, "M") == flu["coverage_by_age_sex"]["18-49"]["M"]
    assert seasonal_flu_coverage("JP", 70, "F") == load_schedule("JP")["influenza"]["coverage_by_age_sex"]["65-99"]["F"]
    # JP models no pediatric flu: the calendar keeps its locale default.
    assert seasonal_flu_coverage("JP", 10, "F") is None


def test_flu_vaccination_candidate_is_the_calendar_rule() -> None:
    assert is_flu_vaccination_candidate(65, 0)
    assert is_flu_vaccination_candidate(30, 2)
    assert not is_flu_vaccination_candidate(64, 1)


def test_enricher_binds_the_flu_dose_to_the_visit_and_synthesises_no_encounter(monkeypatch) -> None:
    @dataclass
    class _Cfg:
        snapshot_date: str = "2025-12-31"
        country: str = "US"
        time_range: tuple = ("2023-01-01", "2025-12-31")

    @dataclass
    class _Rec:
        patient: PatientProfile
        encounters: list = field(default_factory=list)
        immunizations: list = field(default_factory=list)
        clinical_diagnosis: object = None

    @dataclass
    class _Ctx:
        records: list
        master_seed: int = 7
        config: _Cfg = field(default_factory=_Cfg)

    patient = PatientProfile(patient_id="P1", age=72, sex="F", date_of_birth=date(1952, 3, 1))
    visits = [
        Encounter(
            encounter_id=f"ENC-FLU-{year}",
            encounter_type=EncounterType.OUTPATIENT,
            status=EncounterStatus.COMPLETED,
            admission_datetime=datetime(year, 11, 3, 10),
            chief_complaint="Influenza vaccination",
        )
        for year in (2023, 2024, 2025)
    ]
    records = [
        _Rec(patient=patient, encounters=[enc], clinical_diagnosis=SimpleNamespace(admission_diagnosis_code="Z23"))
        for enc in visits
    ]
    monkeypatch.setattr(enricher_mod, "load_schedule", lambda country: {"influenza": _FLU})
    monkeypatch.setattr("clinosim.modules.document.engine.document_enricher", lambda ctx: None)
    enrich_immunizations(_Ctx(records=records))

    in_window = [r for r in records[0].immunizations if r.occurrence_date >= date(2023, 1, 1)]
    by_visit = {r.encounter_id: r.occurrence_date for r in in_window if r.occurrence_date.month >= 6}
    assert by_visit == {f"ENC-FLU-{y}": date(y, 11, 3) for y in (2023, 2024, 2025)}
    for rec in records:
        assert not any(
            e.encounter_id.startswith("ENC-VAX-") and e.admission_datetime.month >= 6 for e in rec.encounters
        )


@pytest.mark.parametrize(("disease_id", "visits"), [("flu_vaccination", 1), ("I10", 2)])
def test_flu_vaccination_visit_starts_no_specialty_follow_up(monkeypatch, disease_id: str, visits: int) -> None:
    """A specialty follow-up fanned out from a flu visit carried its Z23
    reason and no vaccine; only chronic follow-ups fan out."""
    import clinosim.modules.monitoring as monitoring
    import clinosim.simulator.hospital_ops as hospital_ops
    import clinosim.simulator.outpatient as outpatient
    from clinosim.modules.population.engine import LifeEvent
    from clinosim.simulator.phases import _healthcare_calendar as hc

    person = SimpleNamespace(in_population_at=lambda _d: True)
    ctx = SimpleNamespace(
        population=SimpleNamespace(get_person=lambda _pid: person),
        patient_records=[],
        patient_cache={},
        master_seed=1,
        demo={},
        roster=None,
        hospital_ops={},
        config=SimpleNamespace(country="US"),
        followup_data={},
        outpatient_day_ends={},
        inpatient_stays=InpatientStayIndex(),
    )
    monkeypatch.setattr(
        hc, "_activate_cached_person", lambda person, **_k: SimpleNamespace(patient_id="P1", current_medications=[])
    )
    monkeypatch.setattr(hc, "_simulate_outpatient_visit", lambda *_a, **_k: SimpleNamespace(encounters=[]))
    monkeypatch.setattr(hc, "resolve_outpatient_department", lambda *_a, **_k: "internal_medicine")
    monkeypatch.setattr(monitoring, "monitoring_labs_for_patient", lambda *_a, **_k: [])
    monkeypatch.setattr(outpatient, "_specialty_fanout_tick", lambda *_a: [("cardiology", "annual", (2025, None))])
    monkeypatch.setattr(hospital_ops, "resolve_department", lambda name, _ops: name)
    event = LifeEvent(person_id="P1", event_type="chronic_visit", timestamp=date(2025, 11, 2), disease_id=disease_id)
    hc.dispatch_calendar_event(event, ctx)
    assert len(ctx.patient_records) == visits


def test_every_record_of_a_patient_carries_the_same_vaccine_list(monkeypatch) -> None:
    """Lists generated from differing record snapshots gave one dose two
    FHIR ids; the latest record's snapshot now feeds every record."""
    from clinosim.types.patient import ChronicCondition

    @dataclass
    class _Cfg:
        snapshot_date: str = "2025-12-31"
        country: str = "US"
        time_range: tuple = ("2023-01-01", "2025-12-31")

    @dataclass
    class _Rec:
        patient: PatientProfile
        encounters: list = field(default_factory=list)
        immunizations: list = field(default_factory=list)
        clinical_diagnosis: object = None

    @dataclass
    class _Ctx:
        records: list
        master_seed: int = 2  # the engine draws doses in the 2023 and 2025 seasons
        config: _Cfg = field(default_factory=_Cfg)

    def _visit(eid: str, when: datetime) -> Encounter:
        return Encounter(encounter_id=eid, encounter_type=EncounterType.OUTPATIENT, admission_datetime=when)

    early = PatientProfile(patient_id="P1", age=50, sex="M", date_of_birth=date(1974, 3, 1))
    late = PatientProfile(
        patient_id="P1",
        age=50,
        sex="M",
        date_of_birth=date(1974, 3, 1),
        chronic_conditions=[ChronicCondition(code="I10"), ChronicCondition(code="E11.9")],
    )
    records = [
        _Rec(patient=late, encounters=[_visit("E-LATE", datetime(2025, 6, 1, 9))]),
        _Rec(patient=early, encounters=[_visit("E-EARLY", datetime(2023, 3, 1, 9))]),
    ]
    flu = {**_FLU, "coverage_by_age_sex": {"18-99": {"M": 0.5, "F": 0.5}}}
    monkeypatch.setattr(enricher_mod, "load_schedule", lambda country: {"influenza": flu})
    monkeypatch.setattr("clinosim.modules.document.engine.document_enricher", lambda ctx: None)
    enrich_immunizations(_Ctx(records=records))

    def _key(rec):
        return [(r.vaccine_cvx, r.occurrence_date, r.status, r.encounter_id) for r in rec.immunizations]

    assert _key(records[0]) == _key(records[1])
    # The latest snapshot (two chronic conditions) is offered flu visits and
    # had none, so the engine's off-visit doses are not kept.
    assert not [r for r in records[1].immunizations if r.occurrence_date >= date(2023, 9, 1)]
