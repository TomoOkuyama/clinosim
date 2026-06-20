"""Unit tests for immunization generation."""

from datetime import date

import numpy as np
import pytest

pytestmark = pytest.mark.unit


def test_types_importable():
    from clinosim.types.encounter import ImmunizationRecord
    r = ImmunizationRecord(vaccine_cvx="150")
    assert r.status == "completed" and r.primary_source is True


def _patient(age, sex="M", dob_year=None):
    from clinosim.types.patient import PatientProfile
    dob = date((dob_year or (2026 - age)), 1, 1)
    return PatientProfile(patient_id="p1", age=age, sex=sex, date_of_birth=dob)


def _sched():
    from clinosim.modules.immunization.engine import load_schedule
    return load_schedule("US")


def test_min_age_excludes_pneumococcal_for_young():
    from clinosim.modules.immunization.engine import generate_immunizations
    recs = generate_immunizations(
        _patient(40), _sched(), date(2026, 1, 1), np.random.default_rng(1)
    )
    assert all(r.vaccine_cvx != "33" for r in recs)  # PPSV23 min_age 65


def test_all_dates_within_window():
    from clinosim.modules.immunization.engine import generate_immunizations
    as_of = date(2026, 1, 1)
    recs = generate_immunizations(_patient(80), _sched(), as_of, np.random.default_rng(2))
    assert all(r.occurrence_date <= as_of for r in recs)
    # COVID-19 (cvx 309) never before its availability date
    covid = [r for r in recs if r.vaccine_cvx == "309"]
    assert all(r.occurrence_date >= date(2020, 12, 14) for r in covid)


def test_high_coverage_more_than_low_band():
    from clinosim.modules.immunization.engine import generate_immunizations
    # elderly flu coverage (0.68-0.70) >> younger; count flu records across many seeds
    def flu_count(age):
        n = 0
        for s in range(60):
            recs = generate_immunizations(_patient(age), _sched(), date(2026, 1, 1),
                                          np.random.default_rng(s))
            n += sum(1 for r in recs if r.vaccine_cvx == "150")
        return n
    assert flu_count(80) > flu_count(30)


def test_deterministic_same_seed():
    from clinosim.modules.immunization.engine import generate_immunizations
    a = generate_immunizations(
        _patient(70), _sched(), date(2026, 1, 1), np.random.default_rng(7)
    )
    b = generate_immunizations(
        _patient(70), _sched(), date(2026, 1, 1), np.random.default_rng(7)
    )
    assert [(r.vaccine_cvx, r.occurrence_date) for r in a] == [
        (r.vaccine_cvx, r.occurrence_date) for r in b
    ]


def test_covid_never_before_availability():
    from clinosim.modules.immunization.engine import generate_immunizations
    found = 0
    for s in range(40):
        recs = generate_immunizations(
            _patient(80), _sched(), date(2026, 1, 1), np.random.default_rng(s)
        )
        covid = [r for r in recs if r.vaccine_cvx == "309"]
        found += len(covid)
        assert all(r.occurrence_date >= date(2020, 12, 14) for r in covid)
    assert found > 0, "expected at least one COVID record across seeds (high elderly coverage)"


def test_feb29_dob_does_not_crash():
    from clinosim.modules.immunization.engine import generate_immunizations, load_schedule
    from clinosim.types.patient import PatientProfile
    p = PatientProfile(patient_id="p1", age=80, sex="F", date_of_birth=date(1944, 2, 29))
    recs = generate_immunizations(
        p, load_schedule("US"), date(2026, 1, 1), np.random.default_rng(3)
    )
    assert all(r.occurrence_date <= date(2026, 1, 1) for r in recs)
