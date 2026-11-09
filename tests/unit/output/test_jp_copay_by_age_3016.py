"""Issue #3016: the JP copay follows age (and income) on the coverage date, and
後期高齢者医療 starts on the 75th birthday.

健康保険法 / 高齢者医療確保法: 20% before school entry (義務教育就学前), 30% from
school age to 69, 20% at 70-74 (30% for 現役並み所得), from the 75th birthday
後期高齢者医療 at 10% (20% for 一般Ⅱ from 2022-10-01, 30% for 現役並み所得).
"""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.modules.output.fhir_r4.demographics.patient import _build_coverage_resources

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("dob", "on", "income_q", "pct"),
    [
        (date(2021, 6, 1), date(2025, 6, 1), 0.5, 20),  # 4-year-old
        (date(2019, 5, 1), date(2025, 4, 1), 0.5, 20),  # 5, school entry April 2026
        (date(2019, 5, 1), date(2026, 4, 1), 0.5, 30),  # school age
        (date(2019, 3, 1), date(2025, 4, 1), 0.5, 30),  # born Jan-Apr 1: entered school April 2025
        (date(1980, 1, 1), date(2025, 4, 1), 0.01, 30),
        (date(1953, 1, 1), date(2025, 4, 1), 0.5, 20),  # 72
        (date(1953, 1, 1), date(2025, 4, 1), 0.05, 30),  # 72, 現役並み所得
        (date(1945, 1, 1), date(2025, 4, 1), 0.5, 10),  # 80, 一般Ⅰ
        (date(1945, 1, 1), date(2025, 4, 1), 0.15, 20),  # 80, 一般Ⅱ
        (date(1945, 1, 1), date(2021, 4, 1), 0.15, 10),  # 一般Ⅱ before 2022-10-01
        (date(1945, 1, 1), date(2025, 4, 1), 0.03, 30),  # 80, 現役並み所得
    ],
)
def test_jp_copay_by_age_and_income(dob: date, on: date, income_q: float, pct: int) -> None:
    from clinosim.modules.output.fhir_r4.demographics.patient import jp_copay_pct

    assert jp_copay_pct(dob, on, income_q) == pct


def _coverages(dob: str, category: str, encounters: list[dict]) -> list[dict]:
    enr = {"country": "JP", "category": category, "insurer_number": "131011", "member_id": "12345678"}
    if category == "late_elderly":
        enr["insurer_number"] = "39130083"
    patient = {"patient_id": "POP-003779", "date_of_birth": dob, "identity": {"enrollments": [enr]}}
    res = _build_coverage_resources(patient, "JP", encounters=encounters)
    return sorted((r for r in res if r["resourceType"] == "Coverage"), key=lambda c: c["period"]["start"])


def test_a_4_year_olds_copay_is_20_percent() -> None:
    [cov] = _coverages("2021-06-01", "national", [{"admission_datetime": "2025-06-10T10:00:00"}])
    assert cov["costToBeneficiary"][0]["valueQuantity"]["value"] == 20


def test_late_elderly_starts_on_the_75th_birthday() -> None:
    covs = _coverages("1950-09-14", "national", [{"admission_datetime": "2025-12-30T10:00:00"}])
    assert [(c["period"]["start"], c["period"]["end"], c["type"]["text"]) for c in covs] == [
        ("2025-04-01", "2025-09-13", "国民健康保険"),
        ("2025-09-14", "2026-03-31", "後期高齢者医療制度"),
    ]
    assert len({c["id"] for c in covs}) == 2


def test_late_elderly_enrollment_is_not_used_before_75() -> None:
    """Enrolled in 後期 at 75, but the fiscal year began while still 74."""
    covs = _coverages("1946-09-14", "late_elderly", [{"admission_datetime": "2021-12-30T10:00:00"}])
    assert [(c["period"]["start"], c["type"]["text"]) for c in covs] == [
        ("2021-04-01", "国民健康保険"),
        ("2021-09-14", "後期高齢者医療制度"),
    ]
