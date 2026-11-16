"""Issue #3288: a pediatric series' per-dose ``coverage_by_sex`` is the
marginal coverage of that dose (the share of children who receive it), so
the completed series matches the national coverage it cites. The engine
draws dose k (given doses 1..k-1) with the conditional probability
coverage_k / coverage_{k-1}; the number of draws per dose is unchanged."""

from datetime import date, timedelta

import numpy as np
import pytest

pytestmark = pytest.mark.unit

AS_OF = date(2026, 11, 11)


def _dose_counts(schedule: dict, name: str, n: int, *, age_days: int, sex: str = "M") -> list[int]:
    from clinosim.modules.immunization.engine import generate_immunizations
    from clinosim.types.patient import PatientProfile

    cvx = {str(schedule[name]["cvx"])} | {str(p["cvx"]) for p in schedule[name].get("products") or []}
    one = {name: schedule[name]}
    out = []
    for i in range(n):
        dob = AS_OF - timedelta(days=age_days + i % 200)
        child = PatientProfile(patient_id=f"POP-{i:05d}", age=age_days // 365, sex=sex, date_of_birth=dob)
        recs = generate_immunizations(child, one, AS_OF, np.random.default_rng(7000 + i))
        out.append(sum(1 for r in recs if r.status == "completed" and r.vaccine_cvx in cvx))
    return out


def _marginals(vaccine: dict, sex: str) -> list[float]:
    return [float(d["coverage_by_sex"].get(sex, next(iter(d["coverage_by_sex"].values())))) for d in vaccine["doses"]]


def test_conditional_dose_coverage():
    from clinosim.modules.immunization.engine import conditional_dose_coverage

    assert conditional_dose_coverage(0.85, None) == pytest.approx(0.85)
    assert conditional_dose_coverage(0.85, 0.95) == pytest.approx(0.85 / 0.95)
    assert conditional_dose_coverage(0.95, 0.95) == pytest.approx(1.0)
    assert conditional_dose_coverage(0.5, 0.0) == 0.0


@pytest.mark.parametrize("country,name", [("US", "pediatric_dtap"), ("JP", "pediatric_dtap_ipv")])
def test_completed_series_matches_configured_marginal(country, name):
    """Dose 5 (US DTaP) / dose 4 (JP DTaP-IPV) and every earlier dose reach
    the configured marginal coverage, not the product of the per-dose
    values (US DTaP before the fix: 0.95 x 0.93 x 0.92 x 0.86 x 0.85 = 0.59)."""
    from clinosim.modules.immunization.engine import load_schedule

    schedule = load_schedule(country)
    n = 3000
    counts = _dose_counts(schedule, name, n, age_days=2600)
    marg = _marginals(schedule[name], "M")
    for k, m in enumerate(marg, start=1):
        share = sum(c >= k for c in counts) / n
        assert share == pytest.approx(m, abs=0.025), (k, share, m)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_marginal_coverage_never_rises_along_a_series(country):
    """A later dose is only given after the earlier ones, so its marginal
    coverage cannot exceed theirs."""
    from clinosim.modules.immunization.engine import load_schedule

    for name, v in load_schedule(country).items():
        if v.get("frequency") != "pediatric_series":
            continue
        for sex in ("M", "F"):
            marg = _marginals(v, sex)
            assert all(b <= a for a, b in zip(marg, marg[1:])), (country, name, sex, marg)


def test_draw_count_per_dose_unchanged():
    """The coverage threshold changes, the draws do not: a series whose doses
    are all given consumes the same stream as before (one offset draw and
    one coverage draw per dose)."""
    from clinosim.modules.immunization.engine import generate_immunizations
    from clinosim.types.patient import PatientProfile

    doses = [
        {"dose_number": k, "age_days_min": 60 * k, "age_days_max": 60 * k + 20, "coverage_by_sex": {"M": 1.0}}
        for k in (1, 2, 3)
    ]
    sched = {
        "s": {
            "cvx": "20",
            "min_age": 0,
            "frequency": "pediatric_series",
            "available_from": "2000-01-01",
            "doses": doses,
        }
    }
    child = PatientProfile(patient_id="POP-1", age=1, sex="M", date_of_birth=AS_OF - timedelta(days=400))
    rng = np.random.default_rng(11)
    recs = generate_immunizations(child, sched, AS_OF, rng)
    assert len(recs) == 3
    ref = np.random.default_rng(11)
    for _ in range(3):
        ref.integers(0, 21)
        ref.random()
    assert rng.random() == ref.random()
