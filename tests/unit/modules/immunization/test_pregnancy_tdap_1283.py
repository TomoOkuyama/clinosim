"""Regression guard for US maternal Tdap during pregnancy (#1283).

ACIP recommends one dose of Tdap (CVX 115) during each pregnancy at
27-36 weeks gestation to boost maternal antibodies for the newborn's
passive pertussis protection. Real-world US coverage for insured
pregnancies is ~70-80 % (CDC PRAMS). Pre-#1283 the sim did not model
this at all — every US Z34-carrying patient's Immunization stream
was Tdap-free inside their pregnancy interval.

The fix appends `generate_pregnancy_tdap` output to the schedule-driven
Immunization list. Locale-gated to US only (JP has no equivalent
universal maternal pertussis-booster policy).
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.immunization.engine import generate_pregnancy_tdap
from clinosim.types.patient import TemporalStatePeriod

pytestmark = pytest.mark.unit


def _preg_patient(lmp: date, outcome: str = "", pid: str = "PT-PREG") -> SimpleNamespace:
    period = TemporalStatePeriod(
        state_type="pregnancy",
        start_date=lmp,
        end_date=None if not outcome else lmp,
        outcome=outcome,
        metadata={"lmp": lmp, "edd": date.fromordinal(lmp.toordinal() + 280)},
        period_seq=0,
    )
    return SimpleNamespace(patient_id=pid, state_periods=[period])


def test_us_pregnancy_tdap_falls_in_27_to_36_week_window() -> None:
    """A single pregnancy whose full 27-36-week window sits inside the
    sim emits a Tdap dose (at chosen coverage) inside that window."""
    lmp = date(2025, 11, 1)
    patient = _preg_patient(lmp)
    # Seed 42 hits coverage per smoke test.
    rng = np.random.default_rng(42)
    recs = generate_pregnancy_tdap(patient, as_of=date(2026, 9, 12), rng=rng, country="US")
    assert len(recs) == 1
    r = recs[0]
    assert r.vaccine_cvx == "115"
    assert r.status == "completed"
    # 27 weeks = 189 days, 36+6 weeks = 258 days.
    days_from_lmp = (r.occurrence_date - lmp).days
    assert 189 <= days_from_lmp <= 258


def test_us_coverage_hits_expected_band_across_seeds() -> None:
    """Empirical coverage across 200 seeds falls within 60-90 % of the
    configured ~78 % target (allows for the not-done branch too)."""
    lmp = date(2025, 11, 1)
    patient = _preg_patient(lmp)
    hits = 0
    for seed in range(200):
        rng = np.random.default_rng(seed)
        recs = generate_pregnancy_tdap(patient, as_of=date(2026, 9, 12), rng=rng, country="US")
        if recs and recs[0].status != "not-done":
            hits += 1
    assert 0.60 <= hits / 200 <= 0.90, f"coverage out of band: {hits / 200:.3f}"


def test_jp_locale_no_op() -> None:
    """JP locale has no ACIP-equivalent recommendation — do not emit."""
    lmp = date(2025, 11, 1)
    patient = _preg_patient(lmp)
    rng = np.random.default_rng(42)
    recs = generate_pregnancy_tdap(patient, as_of=date(2026, 9, 12), rng=rng, country="JP")
    assert recs == []


def test_aborted_pregnancy_no_tdap() -> None:
    """Pregnancies terminated before term have no 27-36-week window."""
    lmp = date(2025, 11, 1)
    patient = _preg_patient(lmp, outcome="aborted")
    rng = np.random.default_rng(42)
    recs = generate_pregnancy_tdap(patient, as_of=date(2026, 9, 12), rng=rng, country="US")
    assert recs == []


def test_pregnancy_before_27_weeks_no_tdap_yet() -> None:
    """At as_of=today with LMP 3 months ago (~12 weeks GA), the 27-week
    window has not yet opened → no dose."""
    lmp = date(2026, 6, 15)  # ~12 weeks GA as of 2026-09-12
    patient = _preg_patient(lmp)
    rng = np.random.default_rng(42)
    recs = generate_pregnancy_tdap(patient, as_of=date(2026, 9, 12), rng=rng, country="US")
    assert recs == []


def test_patient_without_state_periods_no_op() -> None:
    """Non-pregnant patients (no state_periods) fall through cleanly."""
    patient = SimpleNamespace(patient_id="PT-NP", state_periods=[])
    rng = np.random.default_rng(42)
    recs = generate_pregnancy_tdap(patient, as_of=date(2026, 9, 12), rng=rng, country="US")
    assert recs == []


def test_deterministic_output_same_seed() -> None:
    """Byte-identical output for same (patient, seed) — no wall-clock draws."""
    lmp = date(2025, 11, 1)
    patient1 = _preg_patient(lmp)
    patient2 = _preg_patient(lmp)
    r1 = generate_pregnancy_tdap(patient1, date(2026, 9, 12), np.random.default_rng(7), "US")
    r2 = generate_pregnancy_tdap(patient2, date(2026, 9, 12), np.random.default_rng(7), "US")
    assert [(r.vaccine_cvx, r.occurrence_date, r.status) for r in r1] == [
        (r.vaccine_cvx, r.occurrence_date, r.status) for r in r2
    ]
