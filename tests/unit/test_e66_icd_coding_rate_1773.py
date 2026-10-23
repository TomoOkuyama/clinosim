"""Issue #1773: E66 obesity ICD coded on only the subset of BMI-eligible
persons who would be ICD-coded in real-world US EHR practice.

Pre-fix every BMI-eligible adult (BMI ≥ 25) was ICD-coded, driving
E66 prevalence to 77 % of adults (CDC NHANES 2017-2020 benchmark:
42 % BMI-phenotype, with ~30-50 % ICD-coded in US EHRs). Fix: add a
per-person SHA Bernoulli gate before appending the derived E66 code
(RNG-neutral — no master-stream draw).

Target coding rates (module constants, documented inline):
- Overweight (E66.3): 20 %
- Obesity (E66.9) + Morbid (E66.01): 65 %

Expected cohort-level E66 prevalence post-fix: ~ 42 % BMI-obese × 65 %
+ 30 % overweight × 20 % ≈ 33 % — matches the Issue's ~35 % target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from clinosim.modules.metabolic.engine import (
    _E66_ICD_CODING_RATE_OBESITY,
    _E66_ICD_CODING_RATE_OVERWEIGHT,
    _derive_e66_code,
    _is_e66_icd_coded,
    e66_bmi_enricher,
)

pytestmark = pytest.mark.unit


@dataclass
class _Person:
    person_id: str
    bmi: float
    chronic_conditions: list[str] = field(default_factory=list)


def _ctx_with(*persons: _Person) -> SimpleNamespace:
    population = SimpleNamespace(persons={p.person_id: p for p in persons})
    return SimpleNamespace(population=population)


# ----------------------------------------------------------------------------
# Rate constants ground against Issue #1773 targets
# ----------------------------------------------------------------------------


def test_rate_constants_match_issue_1773_targets() -> None:
    """The per-tier coding rates target real-EHR chart-abstraction
    rates (Kuhlemeier 2023 JGIM, 35-50 % E66 documentation; CDC
    NHANES 42 % BMI-phenotype vs ~35 % Issue target coded)."""
    assert _E66_ICD_CODING_RATE_OVERWEIGHT == 0.20
    assert _E66_ICD_CODING_RATE_OBESITY == 0.65


# ----------------------------------------------------------------------------
# Per-person coin is deterministic + RNG-neutral
# ----------------------------------------------------------------------------


def test_is_e66_icd_coded_deterministic() -> None:
    """SHA Bernoulli must return the same answer for the same
    (person_id, code) pair across calls — bit-reproducibility is the
    whole point of the salt-based pattern."""
    pid = "POP-stub-deterministic"
    first = _is_e66_icd_coded(pid, "E66.9")
    second = _is_e66_icd_coded(pid, "E66.9")
    assert first == second


def test_is_e66_icd_coded_per_person_differs() -> None:
    """Different person_ids with the same code must get independent
    draws — the salt+pid composes into the coin."""
    pid_a = "POP-cohort-A"
    pid_b = "POP-cohort-B"
    # Not a formal uniform check — just a sanity probe that the API
    # is parameterised correctly (two distinct ids give two draws).
    draws = {_is_e66_icd_coded(f"POP-{i}", "E66.9") for i in range(100)}
    assert draws == {True, False}, "100 pids should produce both outcomes"
    _ = pid_a, pid_b


# ----------------------------------------------------------------------------
# Enricher honours the gate
# ----------------------------------------------------------------------------


def test_bmi_below_25_still_gets_no_e66() -> None:
    """BMI < 25 was and remains uncoded. The gate only operates on
    the BMI-eligible subset (BMI ≥ 25)."""
    person = _Person(person_id="POP-below-25", bmi=22.0)
    ctx = _ctx_with(person)
    e66_bmi_enricher(ctx)
    assert not any(c.startswith("E66") for c in person.chronic_conditions)


def test_bmi_eligible_person_may_be_coded_or_skipped() -> None:
    """A BMI≥30 person is a candidate; whether E66.9 lands on their
    chart depends on the SHA coin. Sample 200 synthetic persons at
    the same BMI — the empirical coding rate should sit near the
    documented 65 % obesity rate (±20 % tolerance for 200 draws)."""
    persons = [_Person(person_id=f"POP-sample-{i}", bmi=32.0) for i in range(200)]
    ctx = _ctx_with(*persons)
    e66_bmi_enricher(ctx)
    coded = sum(1 for p in persons if "E66.9" in p.chronic_conditions)
    rate = coded / 200
    assert 0.45 <= rate <= 0.85, f"empirical coding rate {rate:.2%} far outside 65% target (±20%)"


def test_bmi_overweight_coding_rate_matches_target() -> None:
    """Overweight (BMI 25-30) coding rate ≈ 20 % (±15 % tolerance)."""
    persons = [_Person(person_id=f"POP-ow-{i}", bmi=27.0) for i in range(300)]
    ctx = _ctx_with(*persons)
    e66_bmi_enricher(ctx)
    coded = sum(1 for p in persons if "E66.3" in p.chronic_conditions)
    rate = coded / 300
    assert 0.05 <= rate <= 0.35, f"empirical overweight coding rate {rate:.2%} far outside 20% target"


def test_coding_decision_stable_across_runs() -> None:
    """Same person_id + bmi → same final chronic_conditions after two
    separate enricher runs. Bit-reproducibility pin."""
    p1 = _Person(person_id="POP-stable", bmi=34.0)
    p2 = _Person(person_id="POP-stable", bmi=34.0)
    e66_bmi_enricher(_ctx_with(p1))
    e66_bmi_enricher(_ctx_with(p2))
    assert p1.chronic_conditions == p2.chronic_conditions


def test_existing_e66_entry_preserved_without_recoding() -> None:
    """A person who ALREADY carries an E66 code (e.g. from the
    chronic_prevalence yaml path) is left alone — gate does not
    re-roll."""
    p = _Person(person_id="POP-pre-coded", bmi=34.0, chronic_conditions=["E66.9"])
    e66_bmi_enricher(_ctx_with(p))
    assert p.chronic_conditions.count("E66.9") == 1


def test_missing_person_id_skips_coding() -> None:
    """A fixture without a person_id (defensive) does not get coded —
    the SHA coin requires a stable identity."""
    p = _Person(person_id="", bmi=34.0)
    e66_bmi_enricher(_ctx_with(p))
    assert not any(c.startswith("E66") for c in p.chronic_conditions)


# ----------------------------------------------------------------------------
# BMI → tier mapping unchanged
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bmi,expected_tier",
    [
        (18.0, None),
        (24.9, None),
        (25.0, "E66.3"),
        (29.9, "E66.3"),
        (30.0, "E66.9"),
        (39.9, "E66.9"),
        (40.0, "E66.01"),
        (55.0, "E66.01"),
    ],
)
def test_derive_e66_code_tier_mapping_unchanged(bmi: float, expected_tier: str | None) -> None:
    """The BMI tier → ICD mapping is a pure deterministic function and
    stays the same — the Issue #1773 fix only gates ICD coding, not
    the phenotype."""
    assert _derive_e66_code(bmi) == expected_tier
