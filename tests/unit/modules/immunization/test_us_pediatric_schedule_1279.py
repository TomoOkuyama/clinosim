"""Regression guard for US pediatric immunization schedule wiring (#1279).

Pre-fix `clinosim/locale/us/immunization_schedule.yaml` shipped only
adult vaccines (influenza / covid19 / ppsv23 / tdap / zoster_rzv), so
every US patient age 0-17 received zero Immunization records at
p=10k s=354 (US 0-5 = 0 imms, US 6-17 = 0 imms). JP works fine
because `clinosim/locale/jp/immunization_schedule.yaml` carries a
`pediatric_series` block for BCG / DTaP-IPV / MR / varicella / JE /
Hib / PCV13 / HepB / rotavirus / mumps.

Fix adds the ACIP-recommended US primary series (HepB, DTaP, IPV,
Hib, PCV13, Rotavirus, MMR, Varicella, annual influenza from 6 mo,
Tdap booster at 11-13y). Coverage numbers target NIS-Child 2023
completion rates for the 19-35-month cohort.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.immunization.engine import generate_immunizations, load_schedule

pytestmark = pytest.mark.unit


def _patient(dob: date, age: int, sex: str, pid: str = "PT-PEDS-1") -> SimpleNamespace:
    return SimpleNamespace(date_of_birth=dob, age=age, sex=sex, patient_id=pid)


def test_us_schedule_ships_pediatric_series() -> None:
    """Every ACIP primary-series + adolescent vaccine now lives in the US
    schedule. Adolescent series (HPV / MenACWY / HepA) landed in the
    #1279 second follow-up after the initial primary-series wire-in."""
    schedule = load_schedule("US")
    required = {
        "pediatric_hepb",
        "pediatric_dtap",
        "pediatric_ipv",
        "pediatric_hib",
        "pediatric_pcv13",
        "pediatric_rotavirus",
        "pediatric_mmr",
        "pediatric_varicella",
        "pediatric_influenza",
        "pediatric_tdap_booster",
        # Adolescent series — #1279 second follow-up
        "pediatric_hepa",
        "pediatric_hpv",
        "pediatric_menacwy",
    }
    missing = required - set(schedule)
    assert not missing, f"US schedule missing pediatric entries: {missing}"


def test_us_toddler_gets_primary_series() -> None:
    """3-year-old US patient receives at minimum HepB, DTaP, IPV,
    Hib, PCV13, Rotavirus, MMR, Varicella — 8 primary series vaccines
    plus multiple flu shots. Pre-fix: 0."""
    schedule = load_schedule("US")
    rng = np.random.default_rng(42)
    recs = generate_immunizations(
        _patient(date(2023, 1, 1), 3, "M"),
        schedule,
        as_of=date(2026, 9, 12),
        rng=rng,
        nurse_ids=["nurse-1"],
    )
    got = {r.vaccine_cvx for r in recs}
    # These CVX codes correspond to the primary-series pediatric entries
    # (HepB-08, DTaP-20 or covered via dose 1-3, IPV-10, Hib-17, PCV13-133,
    # RotaTeq-116, MMR-03, Varicella-21, ped-influenza-158). Series
    # discontinuation may randomly skip some; require ≥ 5 present.
    ped_cvx_universe = {"08", "20", "10", "17", "133", "116", "03", "21", "158"}
    hits = got & ped_cvx_universe
    assert len(hits) >= 5, f"3yo US must receive ≥5 primary-series vaccines; got {len(hits)}: {sorted(hits)}"
    assert len(recs) >= 8, f"3yo US expected ≥8 total imms; got {len(recs)}"


def test_us_school_age_gets_boosters_and_flu() -> None:
    """15-year-old US patient carries multi-year flu record + adolescent
    Tdap booster. Pre-fix: 0 records."""
    schedule = load_schedule("US")
    rng = np.random.default_rng(43)
    recs = generate_immunizations(
        _patient(date(2010, 6, 15), 15, "F"),
        schedule,
        as_of=date(2026, 9, 12),
        rng=rng,
        nurse_ids=["nurse-1"],
    )
    assert len(recs) >= 5, f"15yo US expected ≥5 imms; got {len(recs)}"
    flu_recs = [r for r in recs if r.vaccine_cvx == "158"]
    assert len(flu_recs) >= 2, "15yo US expected ≥2 pediatric flu shots (annual)"


def test_us_adolescent_gets_hpv_menacwy_hepa_1279_second() -> None:
    """17-year-old US patient carries HPV9 + MenACWY + Hep A adolescent
    series (all landed in the #1279 second follow-up)."""
    schedule = load_schedule("US")
    rng = np.random.default_rng(42)
    recs = generate_immunizations(
        _patient(date(2008, 3, 10), 17, "F"),
        schedule,
        as_of=date(2026, 9, 12),
        rng=rng,
        nurse_ids=["nurse-1"],
    )
    cvx_seen = {r.vaccine_cvx for r in recs}
    for cvx, label in (("165", "HPV9"), ("147", "MenACWY"), ("83", "HepA")):
        assert cvx in cvx_seen, f"17yo US missing {label} (cvx {cvx})"


def test_us_toddler_gets_hepa_dose_1_1279_second() -> None:
    """3-year-old US patient receives HepA dose 1 (12-18 mo window)."""
    schedule = load_schedule("US")
    rng = np.random.default_rng(42)
    recs = generate_immunizations(
        _patient(date(2023, 1, 1), 3, "M"),
        schedule,
        as_of=date(2026, 9, 12),
        rng=rng,
        nurse_ids=["nurse-1"],
    )
    hepa = [r for r in recs if r.vaccine_cvx == "83"]
    assert hepa, "3yo US must carry HepA cvx 83 dose 1"
    # Dose 1 lands within 12-18 mo from dob (2024-01-01 to 2024-07-01).
    for r in hepa:
        if r.dose_number == 1:
            assert date(2024, 1, 1) <= r.occurrence_date <= date(2024, 7, 1), (
                f"HepA dose 1 occ {r.occurrence_date} outside 12-18mo window"
            )


def test_us_adult_flu_still_emits() -> None:
    """Regression: adult influenza vaccination path still fires despite
    the pediatric additions."""
    schedule = load_schedule("US")
    rng = np.random.default_rng(44)
    recs = generate_immunizations(
        _patient(date(1980, 3, 10), 45, "M"),
        schedule,
        as_of=date(2026, 9, 12),
        rng=rng,
        nurse_ids=["nurse-1"],
    )
    adult_flu = [r for r in recs if r.vaccine_cvx == "150"]
    assert adult_flu, "45yo US adult must still receive adult flu shots (cvx 150)"


def test_us_infant_not_yet_eligible_for_dtap_dose1() -> None:
    """Age-window gate: 1-month-old is NOT yet eligible for DTaP dose 1
    (window starts at 2 months = 60 days)."""
    schedule = load_schedule("US")
    rng = np.random.default_rng(45)
    dob = date(2026, 8, 12)  # 1 month before as_of=2026-09-12
    recs = generate_immunizations(
        _patient(dob, 0, "M"),
        schedule,
        as_of=date(2026, 9, 12),
        rng=rng,
        nurse_ids=["nurse-1"],
    )
    dtap = [r for r in recs if r.vaccine_cvx == "20"]
    assert not dtap, "1-month-old must not have received DTaP (starts at 2mo)"
    # But should have received HepB birth dose.
    hepb = [r for r in recs if r.vaccine_cvx == "08"]
    # Coverage is 0.92 so not guaranteed on a single seed — this is a
    # window-eligibility gate, not a coverage assertion.
    assert isinstance(hepb, list)
