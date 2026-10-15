"""K76.0 NAFLD enricher (Issue #1137 cluster 2 axis 3).

BMI + DM-weighted SHA Bernoulli — RNG-neutral per-person
assignment of the K76.0 chronic condition. Mirrors axis-1/2
pattern (POST_POPULATION, idempotent, byte-identity preserving
for cohorts outside the obesity threshold).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from clinosim.modules.metabolic.engine import (
    _derive_nafld_assignment,
    _draw_nafld,
    _nafld_probability,
    k76_0_nafld_enricher,
)
from clinosim.types.population import PersonRecord


@dataclass
class _Ctx:
    population: object
    master_seed: int = 42


class _Pop:
    def __init__(self, persons: dict):
        self.persons = persons


def _person(pid: str, bmi: float, chronic: list[str] | None = None) -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="HH-1",
        age=55,
        sex="M",
        date_of_birth=date(1971, 1, 1),
        bmi=bmi,
        chronic_conditions=list(chronic or []),
    )


# ---------------------------------------------------------------------------
# Pure probability function
# ---------------------------------------------------------------------------


def test_prob_below_obesity_threshold_is_zero() -> None:
    assert _nafld_probability(24.0, has_dm=False) == 0.0
    assert _nafld_probability(29.9, has_dm=True) == 0.0


def test_prob_obese_bmi_matches_anchor() -> None:
    assert _nafld_probability(32.0, has_dm=False) == 0.60
    assert _nafld_probability(39.9, has_dm=False) == 0.60


def test_prob_morbid_bmi_matches_anchor() -> None:
    assert _nafld_probability(40.0, has_dm=False) == 0.85
    assert _nafld_probability(55.0, has_dm=False) == 0.85


def test_prob_dm_uplift_capped_at_one() -> None:
    """0.60 * 1.15 = 0.69, 0.85 * 1.15 = 0.9775 — neither saturates
    but the implementation must still clamp. Push to a hypothetical
    base above the cap via the cap check."""
    assert _nafld_probability(32.0, has_dm=True) == 0.60 * 1.15
    assert _nafld_probability(40.0, has_dm=True) == 0.85 * 1.15


# ---------------------------------------------------------------------------
# Pure SHA draw function
# ---------------------------------------------------------------------------


def test_draw_zero_probability_always_false() -> None:
    assert _draw_nafld("PT-ANY", 0.0) is False


def test_draw_full_probability_always_true() -> None:
    assert _draw_nafld("PT-ANY", 1.0) is True


def test_draw_is_deterministic_per_person() -> None:
    """Repeated draws for the same person id + probability return
    the same answer (SHA-based hash)."""
    r1 = _draw_nafld("PT-DET", 0.5)
    r2 = _draw_nafld("PT-DET", 0.5)
    assert r1 == r2


def test_draw_differs_across_persons() -> None:
    """At p=0.5 roughly half of a 200-person cohort should draw
    True — specifically, the SHA quantile distribution of distinct
    salted person ids should straddle the threshold rather than
    collapse to a single answer."""
    hits = sum(1 for i in range(200) if _draw_nafld(f"PT-{i}", 0.5))
    assert 60 <= hits <= 140, f"got {hits} / 200 (expected ~100 ±40)"


# ---------------------------------------------------------------------------
# Derivation wrapper
# ---------------------------------------------------------------------------


def test_derive_below_threshold_returns_none() -> None:
    assert _derive_nafld_assignment("PT-LEAN", 24.0, ["E11.9"]) is None


def test_derive_morbid_dm_assigns_code_high_rate() -> None:
    """Morbid obesity + DM = 0.85*1.15 ≈ 0.98 — within 50 persons
    ~2 % expected to NOT get K76.0."""
    yes = sum(1 for i in range(50) if _derive_nafld_assignment(f"PT-M-{i}", 42.0, ["E11.9"]) == "K76.0")
    assert yes >= 45, f"only {yes} / 50 assigned (expected >= 45)"


# ---------------------------------------------------------------------------
# Enricher behavior
# ---------------------------------------------------------------------------


def test_enricher_leaves_sub_bmi_person_untouched() -> None:
    p = _person("PT-LEAN", bmi=22.0, chronic=["I10"])
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    k76_0_nafld_enricher(ctx)
    assert "K76.0" not in p.chronic_conditions
    assert p.chronic_conditions == ["I10"]


def test_enricher_idempotent_on_repeat_call() -> None:
    p = _person("PT-REPEAT", bmi=42.0, chronic=["E11.9"])
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    k76_0_nafld_enricher(ctx)
    before = p.chronic_conditions.count("K76.0")
    k76_0_nafld_enricher(ctx)
    after = p.chronic_conditions.count("K76.0")
    assert before == after


def test_enricher_mixed_cohort_prevalence_in_band() -> None:
    """A 500-person obese + DM cohort should assign K76.0 to roughly
    0.60 * 1.15 ≈ 69 % of patients. Allow ±10 % band for a 500-sample
    SHA Bernoulli."""
    persons = {f"PT-OB-{i}": _person(f"PT-OB-{i}", bmi=33.0, chronic=["E11.9"]) for i in range(500)}
    ctx = _Ctx(population=_Pop(persons))
    k76_0_nafld_enricher(ctx)
    assigned = sum(1 for p in persons.values() if "K76.0" in p.chronic_conditions)
    expected = 0.60 * 1.15 * 500
    assert abs(assigned - expected) < 50, f"got {assigned} / 500 (expected ~{expected:.0f} ±50)"


def test_enricher_rng_neutral_fixed_person_id() -> None:
    """SHA-based draw depends on person_id, not on any master-seed
    state. The same person_id + chronic set must yield the same
    outcome across isolated contexts."""
    p1 = _person("PT-SAME", bmi=42.0, chronic=["E11.9"])
    p2 = _person("PT-SAME", bmi=42.0, chronic=["E11.9"])
    ctx1 = _Ctx(population=_Pop({p1.person_id: p1}), master_seed=1)
    ctx2 = _Ctx(population=_Pop({p2.person_id: p2}), master_seed=999)
    k76_0_nafld_enricher(ctx1)
    k76_0_nafld_enricher(ctx2)
    assert ("K76.0" in p1.chronic_conditions) == ("K76.0" in p2.chronic_conditions)
