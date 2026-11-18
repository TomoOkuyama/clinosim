"""Issue #3301: JP 5-valent DPT-IPV-Hib for children born from 2024-02-01 (the
4-valent + Hib series for earlier births), and the MR second-period dose for
a child who missed the first one (定期接種実施要領 第2 各論 1 (1), 2 (1) イ)."""

from datetime import date, timedelta

import numpy as np
import pytest

pytestmark = pytest.mark.unit

AS_OF = date(2026, 11, 11)


def _recs(dob: date, i: int, as_of: date = AS_OF):
    from clinosim.modules.immunization.engine import generate_immunizations, load_schedule
    from clinosim.types.patient import PatientProfile

    child = PatientProfile(patient_id=f"POP-{i:05d}", age=max(0, (as_of - dob).days // 365), sex="M", date_of_birth=dob)
    return generate_immunizations(child, load_schedule("JP"), as_of, np.random.default_rng(9000 + i))


def _count(recs, cvx):
    return sum(1 for r in recs if r.vaccine_cvx == cvx and r.status == "completed")


def test_cvx_120_is_registered_in_both_languages():
    from clinosim.codes import lookup

    assert lookup("cvx", "120", "en") == "DTaP-Hib-IPV"
    assert "五種混合" in lookup("cvx", "120", "ja")


def test_post_switch_birth_gets_five_valent_not_four_valent_or_hib():
    boundary = date(2024, 2, 1)
    for i in range(60):
        recs = _recs(boundary + timedelta(days=i * 11), i)
        assert _count(recs, "106") == 0 and _count(recs, "17") == 0
    n5 = [_count(_recs(boundary + timedelta(days=i * 11), i), "120") for i in range(60)]
    assert max(n5) == 4 and sum(c >= 1 for c in n5) > 45


def test_pre_switch_birth_keeps_four_valent_and_hib():
    for i in range(60):
        recs = _recs(date(2023, 6, 1) + timedelta(days=i * 3), i)
        assert _count(recs, "120") == 0
    counts = [_count(_recs(date(2023, 6, 1) + timedelta(days=i * 3), i), "106") for i in range(60)]
    assert max(counts) == 4


def test_schedule_for_birth_boundaries():
    from clinosim.modules.immunization.engine import load_schedule, schedule_for_birth

    s = load_schedule("JP")
    last_old = schedule_for_birth(s, date(2024, 1, 31))
    first_new = schedule_for_birth(s, date(2024, 2, 1))
    assert "pediatric_dtap_ipv" in last_old and "pediatric_hib" in last_old and "pediatric_dtap_ipv_hib" not in last_old
    assert "pediatric_dtap_ipv_hib" in first_new and not {"pediatric_dtap_ipv", "pediatric_hib"} & set(first_new)
    assert "pediatric_dtap_ipv_hib" in schedule_for_birth(s, None)
    # Series windows follow the MHLW standard schedule (primary 2-7 months, 3 doses >= 20 days).
    doses = s["pediatric_dtap_ipv_hib"]["doses"]
    assert [d["dose_number"] for d in doses] == [1, 2, 3, 4]
    assert all(d["age_days_max"] <= 213 for d in doses[:3]) and doses[3]["min_interval_days"] >= 182
    assert s["pediatric_dtap_ipv_hib"]["cvx"] == "120"


def test_us_schedule_has_no_birth_gate():
    from clinosim.modules.immunization.engine import load_schedule

    assert not any("birth_from" in v or "birth_until" in v for v in load_schedule("US").values())


def test_mr_second_dose_for_child_who_missed_the_first():
    dob = date(2019, 1, 10)  # school entry 2025-04; 第2期 year 2024-04 to 2025-03
    as_of = date(2025, 6, 1)
    n = 3000
    first = both = second_only = 0
    for i in range(n):
        recs = [r for r in _recs(dob + timedelta(days=i % 200), i, as_of) if r.vaccine_cvx == "04"]
        nums = {r.dose_number for r in recs if r.status == "completed"}
        first += 1 in nums
        both += nums == {1, 2}
        second_only += nums == {2}
    # Dose 1 is outside the sim's range (before as_of window is irrelevant: the
    # windows both open before as_of), so dose 1 comes at 1-2 years.
    assert second_only > 0, "a child who missed dose 1 still gets the 第2期 dose"
    # The share of children with the 第2期 dose stays the national 92.0%.
    with_second = (both + second_only) / n
    assert with_second == pytest.approx(0.92, abs=0.02)
    # A child who missed dose 1 gets it at the lower assumed rate (0.5).
    missed = n - first
    assert second_only / missed == pytest.approx(0.5, abs=0.1)


def test_independent_dose_coverage_preserves_marginal():
    from clinosim.modules.immunization.engine import independent_dose_coverage

    c = independent_dose_coverage(0.92, 0.949, 0.5)
    assert 0.949 * c + 0.051 * 0.5 == pytest.approx(0.92)
    assert independent_dose_coverage(0.92, 0.0, 0.5) == pytest.approx(0.92)


def test_mr_second_dose_not_before_interval_and_other_series_still_gap_free():
    for i in range(200):
        recs = sorted(
            (r for r in _recs(date(2018, 9, 1) + timedelta(days=i), i, date(2025, 6, 1)) if r.vaccine_cvx == "04"),
            key=lambda r: r.occurrence_date,
        )
        for a, b in zip(recs, recs[1:]):
            assert (b.occurrence_date - a.occurrence_date).days >= 27
