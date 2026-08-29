"""Unit tests for immunization generation."""

from datetime import date

import numpy as np
import pytest

pytestmark = pytest.mark.unit


def test_types_importable():
    from clinosim.types.encounter import ImmunizationRecord

    r = ImmunizationRecord(vaccine_cvx="150")
    assert r.status == "completed" and r.primary_source is True


def _sched():
    from clinosim.modules.immunization.engine import load_schedule

    return load_schedule("US")


def test_min_age_excludes_pneumococcal_for_young(patient_factory):
    from clinosim.modules.immunization.engine import generate_immunizations

    recs = generate_immunizations(patient_factory(age=40), _sched(), date(2026, 1, 1), np.random.default_rng(1))
    assert all(r.vaccine_cvx != "33" for r in recs)  # PPSV23 min_age 65


def test_all_dates_within_window(patient_factory):
    from clinosim.modules.immunization.engine import generate_immunizations

    as_of = date(2026, 1, 1)
    recs = generate_immunizations(patient_factory(age=80), _sched(), as_of, np.random.default_rng(2))
    assert all(r.occurrence_date <= as_of for r in recs)
    # COVID-19 (cvx 309) never before its availability date
    covid = [r for r in recs if r.vaccine_cvx == "309"]
    assert all(r.occurrence_date >= date(2020, 12, 14) for r in covid)


def test_history_years_caps_annual_lookback(patient_factory):
    """An annual vaccine with history_years=N only generates within the last N years
    (models EHR data retention — avoids decades of accumulated flu shots)."""
    from clinosim.modules.immunization.engine import generate_immunizations

    as_of = date(2026, 1, 1)
    schedule = {
        "influenza": {
            "cvx": "150",
            "min_age": 18,
            "frequency": "annual",
            "season_month": 10,
            "available_from": "2000-01-01",
            "history_years": 10,
            "coverage_by_age_sex": {"18-99": {"M": 1.0, "F": 1.0}},
        }
    }
    recs = generate_immunizations(patient_factory(age=80), schedule, as_of, np.random.default_rng(2))
    flu = [r for r in recs if r.vaccine_cvx == "150"]
    # With coverage 1.0 and a 10-year lookback, at most ~11 seasons (2016-2026), never 26.
    assert flu, "expected flu records"
    assert all(r.occurrence_date >= date(2016, 1, 1) for r in flu)
    assert len(flu) <= 11


def test_high_coverage_more_than_low_band(patient_factory):
    from clinosim.modules.immunization.engine import generate_immunizations

    # elderly flu coverage (0.68-0.70) >> younger; count flu records across many seeds
    def flu_count(age):
        n = 0
        for s in range(60):
            recs = generate_immunizations(
                patient_factory(age=age), _sched(), date(2026, 1, 1), np.random.default_rng(s)
            )
            n += sum(1 for r in recs if r.vaccine_cvx == "150")
        return n

    assert flu_count(80) > flu_count(30)


def test_deterministic_same_seed(patient_factory):
    from clinosim.modules.immunization.engine import generate_immunizations

    a = generate_immunizations(patient_factory(age=70), _sched(), date(2026, 1, 1), np.random.default_rng(7))
    b = generate_immunizations(patient_factory(age=70), _sched(), date(2026, 1, 1), np.random.default_rng(7))
    assert [(r.vaccine_cvx, r.occurrence_date) for r in a] == [(r.vaccine_cvx, r.occurrence_date) for r in b]


def test_covid_never_before_availability(patient_factory):
    from clinosim.modules.immunization.engine import generate_immunizations

    found = 0
    for s in range(40):
        recs = generate_immunizations(patient_factory(age=80), _sched(), date(2026, 1, 1), np.random.default_rng(s))
        covid = [r for r in recs if r.vaccine_cvx == "309"]
        found += len(covid)
        assert all(r.occurrence_date >= date(2020, 12, 14) for r in covid)
    assert found > 0, "expected at least one COVID record across seeds (high elderly coverage)"


def test_feb29_dob_does_not_crash():
    from clinosim.modules.immunization.engine import generate_immunizations, load_schedule
    from clinosim.types.patient import PatientProfile

    p = PatientProfile(patient_id="p1", age=80, sex="F", date_of_birth=date(1944, 2, 29))
    recs = generate_immunizations(p, load_schedule("US"), date(2026, 1, 1), np.random.default_rng(3))
    assert all(r.occurrence_date <= date(2026, 1, 1) for r in recs)


def test_issue_926_immunization_enricher_caps_as_of_at_date_of_death():
    """Issue #926: `_as_of` clamps at date_of_death so a deceased patient
    never receives an immunization after their recorded death.

    Simulates the p=10000 real-world case: patient died 2025-10-05,
    snapshot date 2026-03-31 — without the cap the flu scheduler would
    happily emit a 2025-11-01 dose.
    """
    from dataclasses import dataclass, field

    from clinosim.modules.immunization.enricher import _as_of
    from clinosim.types.patient import PatientProfile

    @dataclass
    class _Cfg:
        snapshot_date: str = "2026-03-31"
        country: str = "US"

    @dataclass
    class _Ctx:
        config: _Cfg = field(default_factory=_Cfg)

    @dataclass
    class _Rec:
        patient: PatientProfile | None = None
        encounters: list = field(default_factory=list)

    p_alive = PatientProfile(patient_id="alive", age=70, sex="M", date_of_birth=date(1955, 1, 1))
    p_dead = PatientProfile(
        patient_id="dead",
        age=70,
        sex="M",
        date_of_birth=date(1955, 1, 1),
        date_of_death=date(2025, 10, 5),
    )

    ctx = _Ctx()
    # Living patient: as_of equals snapshot_date.
    assert _as_of(ctx, _Rec(patient=p_alive)) == date(2026, 3, 31)
    # Deceased patient: as_of clamped at date_of_death.
    assert _as_of(ctx, _Rec(patient=p_dead)) == date(2025, 10, 5)


def test_issue_926_no_post_mortem_flu_when_death_precedes_season():
    """End-to-end enricher path: a patient who died 2025-10-05 must not
    receive the 2025-11-01 flu shot even at coverage 1.0.
    """
    from dataclasses import dataclass, field

    import clinosim.modules.immunization.enricher as mod
    from clinosim.modules.immunization.enricher import enrich_immunizations
    from clinosim.types.patient import PatientProfile

    schedule_yaml = {
        "influenza": {
            "cvx": "150",
            "min_age": 6,
            "frequency": "annual",
            "season_month": 11,
            "available_from": "2000-01-01",
            "history_years": 5,
            "coverage_by_age_sex": {"6-99": {"M": 1.0, "F": 1.0}},
        }
    }

    @dataclass
    class _Cfg:
        snapshot_date: str = "2026-03-31"
        country: str = "US"

    @dataclass
    class _Rec:
        patient: PatientProfile | None = None
        encounters: list = field(default_factory=list)
        immunizations: list = field(default_factory=list)

    @dataclass
    class _Ctx:
        records: list = field(default_factory=list)
        master_seed: int = 42
        config: _Cfg = field(default_factory=_Cfg)

    p_dead = PatientProfile(
        patient_id="dead",
        age=70,
        sex="M",
        date_of_birth=date(1955, 1, 1),
        date_of_death=date(2025, 10, 5),
    )
    rec = _Rec(patient=p_dead)
    ctx = _Ctx(records=[rec])

    orig_loader = mod.load_schedule
    try:
        mod.load_schedule = lambda country: schedule_yaml
        enrich_immunizations(ctx)
    finally:
        mod.load_schedule = orig_loader

    assert all(r.occurrence_date <= date(2025, 10, 5) for r in rec.immunizations), (
        "no immunization may be dated after the patient's date_of_death"
    )
    assert all(r.occurrence_date != date(2025, 11, 1) for r in rec.immunizations), (
        "the 2025-11-01 flu shot must not fire for a patient who died 2025-10-05"
    )
