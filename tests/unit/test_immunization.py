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


# ---------------------------------------------------------------------------
# Issue #921 regression: flu seasonal distribution + COVID wave epochs
# ---------------------------------------------------------------------------


def _flu_yaml_with_seasonal(coverage: float = 1.0) -> dict:
    return {
        "influenza": {
            "cvx": "150",
            "min_age": 18,
            "frequency": "annual",
            "season_month": 11,  # legacy fallback — should NOT be used when seasonal_distribution present
            "available_from": "2000-01-01",
            "history_years": 10,
            "seasonal_distribution": {"10": 0.15, "11": 0.40, "12": 0.30, "1": 0.10, "2": 0.05},
            "coverage_by_age_sex": {"18-99": {"M": coverage, "F": coverage}},
        }
    }


def test_issue_921_flu_seasonal_distribution_covers_multiple_months(patient_factory):
    """Flu doses spread across Oct-Feb per seasonal_distribution instead of
    collapsing to one calendar month (Issue #921 root cause). Aggregated
    across seeds we should see all five configured months populated with the
    November share dominating."""
    from collections import Counter

    from clinosim.modules.immunization.engine import generate_immunizations

    as_of = date(2026, 1, 1)
    sched = _flu_yaml_with_seasonal(coverage=1.0)
    months: Counter = Counter()
    # 40 seeds x 80yo patient with 10y history = ~400 flu doses
    for s in range(40):
        recs = generate_immunizations(patient_factory(age=80), sched, as_of, np.random.default_rng(s))
        for r in recs:
            if r.vaccine_cvx == "150" and r.status == "completed":
                months[r.occurrence_date.month] += 1

    # Every configured month must appear at least once (no single-month collapse)
    for m in (10, 11, 12, 1, 2):
        assert months[m] > 0, f"month {m} unpopulated — flu still collapsed. hist={dict(months)}"
    # Only configured months appear
    assert set(months).issubset({10, 11, 12, 1, 2}), f"unexpected months: {dict(months)}"
    # November should dominate but must not be 100% (defeats the whole fix)
    total = sum(months.values())
    nov_share = months[11] / total
    assert 0.25 < nov_share < 0.70, f"November share {nov_share:.2%} out of expected 30-55%; hist={dict(months)}"


def test_issue_921_flu_uses_default_month_when_no_seasonal_distribution(patient_factory):
    """Backward compat: a yaml WITHOUT seasonal_distribution keeps the
    legacy fixed season_month behaviour so existing US/JP schedules with
    only season_month set stay bit-identical."""
    from clinosim.modules.immunization.engine import generate_immunizations

    as_of = date(2026, 1, 1)
    sched = {
        "influenza": {
            "cvx": "150",
            "min_age": 18,
            "frequency": "annual",
            "season_month": 10,
            "available_from": "2000-01-01",
            "history_years": 5,
            "coverage_by_age_sex": {"18-99": {"M": 1.0, "F": 1.0}},
        }
    }
    recs = generate_immunizations(patient_factory(age=70), sched, as_of, np.random.default_rng(1))
    flu = [r for r in recs if r.vaccine_cvx == "150" and r.status == "completed"]
    assert flu
    assert all(r.occurrence_date.month == 10 for r in flu)


def test_issue_921_flu_deterministic_same_seed(patient_factory):
    """RNG neutrality: same patient + same seed yields identical dose dates."""
    from clinosim.modules.immunization.engine import generate_immunizations

    as_of = date(2026, 1, 1)
    sched = _flu_yaml_with_seasonal(coverage=1.0)
    a = generate_immunizations(patient_factory(age=70), sched, as_of, np.random.default_rng(11))
    b = generate_immunizations(patient_factory(age=70), sched, as_of, np.random.default_rng(11))
    assert [(r.vaccine_cvx, r.occurrence_date, r.status) for r in a] == [
        (r.vaccine_cvx, r.occurrence_date, r.status) for r in b
    ]


def _covid_yaml_with_epochs() -> dict:
    return {
        "covid19": {
            "cvx": "309",
            "min_age": 18,
            "frequency": "once",
            "available_from": "2021-02-17",
            "wave_epochs": [
                {
                    "name": "initial_rollout",
                    "start": "2021-04-01",
                    "end": "2021-09-30",
                    "age_weight": {"18-49": 0.05, "50-64": 0.15, "65-99": 0.55},
                    "monthly_curve": {"4": 0.05, "5": 0.20, "6": 0.30, "7": 0.20, "8": 0.15, "9": 0.10},
                },
                {
                    "name": "primary_series_ramp",
                    "start": "2021-10-01",
                    "end": "2022-03-31",
                    "age_weight": {"18-49": 0.40, "50-64": 0.30, "65-99": 0.15},
                    "monthly_curve": {"10": 0.20, "11": 0.30, "12": 0.20, "1": 0.15, "2": 0.10, "3": 0.05},
                },
                {
                    "name": "annual_maintenance",
                    "start": "2023-09-01",
                    "end": "2026-12-31",
                    "age_weight": {"18-49": 0.10, "50-64": 0.15, "65-99": 0.10},
                    "monthly_curve": {"9": 0.15, "10": 0.35, "11": 0.30, "12": 0.15, "1": 0.05},
                },
            ],
            "coverage_by_age_sex": {"18-99": {"M": 1.0, "F": 1.0}},
        }
    }


def test_issue_921_covid_wave_epochs_cluster_not_uniform(patient_factory):
    """COVID doses cluster into wave epochs (fall booster, spring rollout),
    not the pre-fix uniform 55-88 doses per month."""
    from collections import Counter

    from clinosim.modules.immunization.engine import generate_immunizations

    as_of = date(2026, 8, 31)
    sched = _covid_yaml_with_epochs()
    by_month: Counter = Counter()  # (year, month)
    # Mix age bands so all epochs get sampled
    ages = [30, 55, 70]
    for age in ages:
        for s in range(300):
            recs = generate_immunizations(
                patient_factory(age=age),
                sched,
                as_of,
                np.random.default_rng(s + 1000 * age),
            )
            for r in recs:
                if r.vaccine_cvx == "309" and r.status == "completed":
                    by_month[(r.occurrence_date.year, r.occurrence_date.month)] += 1

    total = sum(by_month.values())
    assert total > 100, f"expected many COVID doses across seeds, got {total}"

    # No dose before availability
    assert all(y >= 2021 for (y, _) in by_month), f"pre-availability doses: {sorted(by_month)}"

    # Never uniform (0 doses in ~half of months since epochs don't cover them):
    # months like 2022-07 (between primary_series_ramp end 2022-03 and
    # annual_maintenance start 2023-09) should be empty.
    empty_months = 0
    y, m = 2021, 4
    while (y, m) <= (2026, 8):
        if by_month.get((y, m), 0) == 0:
            empty_months += 1
        m += 1
        if m == 13:
            m = 1
            y += 1
    assert empty_months >= 10, (
        f"expected at least 10 empty months (wave gaps), got {empty_months}; distribution may still be near-uniform"
    )

    # Fall months in annual_maintenance (2024-10, 2025-10) should be denser
    # than early 2022 gap month.
    fall_2024 = by_month.get((2024, 10), 0) + by_month.get((2024, 11), 0)
    gap_2022 = by_month.get((2022, 7), 0) + by_month.get((2022, 8), 0)
    assert fall_2024 > gap_2022, f"fall-2024 peak ({fall_2024}) not greater than 2022 gap ({gap_2022})"


def test_issue_921_covid_epoch_falls_within_configured_windows(patient_factory):
    """Every COVID dose date must lie inside one of the epoch windows."""
    from clinosim.modules.immunization.engine import generate_immunizations

    as_of = date(2026, 8, 31)
    sched = _covid_yaml_with_epochs()
    windows = [
        (date(2021, 4, 1), date(2021, 9, 30)),
        (date(2021, 10, 1), date(2022, 3, 31)),
        (date(2023, 9, 1), date(2026, 12, 31)),
    ]
    for age in (30, 55, 70):
        for s in range(50):
            recs = generate_immunizations(
                patient_factory(age=age),
                sched,
                as_of,
                np.random.default_rng(s + age),
            )
            for r in recs:
                if r.vaccine_cvx == "309" and r.status == "completed":
                    d = r.occurrence_date
                    assert any(lo <= d <= hi for (lo, hi) in windows), (
                        f"COVID dose {d} landed outside every wave epoch window"
                    )
                    assert d <= as_of


def test_issue_921_covid_falls_back_when_no_epoch_matches(patient_factory):
    """A patient whose eligibility window falls entirely outside every wave
    epoch must not receive a dose (returning None from the picker → skip)."""
    from clinosim.modules.immunization.engine import generate_immunizations

    # as_of = 2020-06-30 predates every epoch start (earliest 2021-04-01)
    as_of = date(2020, 6, 30)
    sched = _covid_yaml_with_epochs()
    # override availability so start ≤ as_of
    sched["covid19"]["available_from"] = "2019-01-01"
    total = 0
    for s in range(30):
        recs = generate_immunizations(patient_factory(age=70), sched, as_of, np.random.default_rng(s))
        total += sum(1 for r in recs if r.vaccine_cvx == "309" and r.status == "completed")
    assert total == 0, f"expected no COVID doses when no epoch overlaps window, got {total}"


def test_issue_921_covid_epoch_death_gate_preserved(patient_factory):
    """Regression against #928: even after seasonality/epoch sampling, no
    dose may fall after a patient's date_of_death. Uses the enricher path
    (which is what applies the death clamp)."""
    from dataclasses import dataclass, field

    import clinosim.modules.immunization.enricher as mod
    from clinosim.modules.immunization.enricher import enrich_immunizations
    from clinosim.types.patient import PatientProfile

    @dataclass
    class _Cfg:
        snapshot_date: str = "2026-08-31"
        country: str = "JP"

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
        patient_id="dead-921",
        age=70,
        sex="M",
        date_of_birth=date(1955, 1, 1),
        date_of_death=date(2022, 6, 15),  # dies mid-way through the epochs
    )
    rec = _Rec(patient=p_dead)
    ctx = _Ctx(records=[rec])

    # Force strong signal: high coverage & epochs
    schedule_yaml = {
        "influenza": _flu_yaml_with_seasonal(coverage=1.0)["influenza"],
        "covid19": _covid_yaml_with_epochs()["covid19"],
    }

    orig = mod.load_schedule
    try:
        mod.load_schedule = lambda country: schedule_yaml
        enrich_immunizations(ctx)
    finally:
        mod.load_schedule = orig

    assert rec.immunizations, "expected some doses to fire pre-death"
    assert all(r.occurrence_date <= date(2022, 6, 15) for r in rec.immunizations), (
        "post-mortem dose emitted — #928 death gate regressed"
    )
