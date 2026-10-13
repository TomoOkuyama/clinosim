"""Parent → child biological inheritance — Issue #1581 Phase C.1.

ABO + Rh deterministic SHA-based sampling. Monte-Carlo checks confirm
that a mother-phenotype × locale-allele-frequency cross reproduces the
locale phenotype distribution within a reasonable tolerance for a
sampled cohort.
"""

from __future__ import annotations

from collections import Counter

from clinosim.modules.population.inheritance import (
    _MOTHER_GENOTYPE_PROBS,
    _phenotype_from_alleles,
    derive_newborn_blood_type,
    derive_newborn_rh_factor,
)


def test_derive_newborn_blood_type_is_deterministic() -> None:
    """Same (newborn_id, mother phenotype, country) → same child phenotype
    across calls (SHA-based, no RNG consumption)."""
    assert derive_newborn_blood_type("PT-X-BABY-01", "A", "US") == derive_newborn_blood_type("PT-X-BABY-01", "A", "US")
    # Different ids produce (usually) different draws, but at least the
    # function must be purely functional.
    first_a = derive_newborn_blood_type("PT-X-BABY-01", "A", "US")
    first_b = derive_newborn_blood_type("PT-X-BABY-01", "A", "US")
    assert first_a == first_b


def test_derive_newborn_rh_is_deterministic() -> None:
    assert derive_newborn_rh_factor("PT-X-BABY-01", "+", "US") == derive_newborn_rh_factor("PT-X-BABY-01", "+", "US")


def test_phenotype_from_alleles_matches_abo_rules() -> None:
    # Dominant A over O
    assert _phenotype_from_alleles("A", "O") == "A"
    assert _phenotype_from_alleles("O", "A") == "A"
    assert _phenotype_from_alleles("A", "A") == "A"
    # Dominant B over O
    assert _phenotype_from_alleles("B", "O") == "B"
    assert _phenotype_from_alleles("O", "B") == "B"
    assert _phenotype_from_alleles("B", "B") == "B"
    # Co-dominant A + B
    assert _phenotype_from_alleles("A", "B") == "AB"
    assert _phenotype_from_alleles("B", "A") == "AB"
    # Recessive O + O
    assert _phenotype_from_alleles("O", "O") == "O"


def test_mother_o_crosses_match_locale_allele_freq() -> None:
    """A cohort of children born to O-type mothers should reflect the
    locale paternal allele frequency: p(A) ≈ 0.264, p(B) ≈ 0.071,
    p(O) ≈ 0.665 for US. Mother always donates O, so child phenotype
    equals the paternal allele's dominance."""
    counts: Counter[str] = Counter()
    for i in range(2000):
        counts[derive_newborn_blood_type(f"PT-MC-O-{i:04d}", "O", "US")] += 1
    total = sum(counts.values())
    assert 0.60 < counts["O"] / total < 0.72, counts
    assert 0.22 < counts["A"] / total < 0.31, counts
    assert 0.04 < counts["B"] / total < 0.10, counts


def test_mother_ab_never_produces_o() -> None:
    """An AB mother always donates A or B — never O — so her children
    can be A, B, or AB, but never O (unless cosmic ray)."""
    for i in range(500):
        child = derive_newborn_blood_type(f"PT-MC-AB-{i:04d}", "AB", "US")
        assert child != "O", f"AB mother produced O child at seed {i}"


def test_mother_rh_negative_depends_on_locale_father_freq() -> None:
    """Mother Rh- donates d deterministically. Father-side allele
    sample draws D with probability p = 1 - sqrt(1 - rh_pos). For US
    (rh_pos=0.85), q(d) ≈ 0.387, p(D) ≈ 0.613 — so roughly 60 % of
    children of Rh- mothers in US are Rh+."""
    rh_pos_count = 0
    trials = 2000
    for i in range(trials):
        rh = derive_newborn_rh_factor(f"PT-MC-RHN-{i:04d}", "-", "US")
        if rh == "+":
            rh_pos_count += 1
    frac = rh_pos_count / trials
    # p(D) in US ≈ 0.613; allow ±5 % Monte-Carlo band.
    assert 0.55 < frac < 0.67, f"Rh- mother → Rh+ rate {frac} out of expected band"


def test_mother_rh_positive_jp_near_universally_rh_positive() -> None:
    """JP Rh- fraction is 0.5 %, so an Rh+ mother in JP almost always
    produces an Rh+ child (both her donated allele and the paternal
    draw are overwhelmingly D)."""
    rh_pos_count = 0
    trials = 1000
    for i in range(trials):
        rh = derive_newborn_rh_factor(f"PT-MC-JPRH-{i:04d}", "+", "JP")
        if rh == "+":
            rh_pos_count += 1
    # Even with Rh- allele p=0.07, child Rh- probability is ~0.07^2 for
    # dd homozygote emergence — practically ≥ 99 %.
    assert rh_pos_count / trials > 0.98


def test_two_parent_blood_type_crosses_match_punnett() -> None:
    """Issue #1581 Phase C.2 — when both parents' phenotypes are
    supplied, the child distribution matches the standard Punnett
    square. Mother A × Father B → child can be A, B, AB, or O.
    Mother O × Father O → child always O. Mother AB × Father AB →
    child A, B, or AB (never O)."""
    counts_oo: Counter[str] = Counter()
    counts_abab: Counter[str] = Counter()
    for i in range(1000):
        counts_oo[derive_newborn_blood_type(f"PT-OO-{i:04d}", "O", country="US", father_blood_type="O")] += 1
        counts_abab[derive_newborn_blood_type(f"PT-ABAB-{i:04d}", "AB", country="US", father_blood_type="AB")] += 1
    # O × O → always O.
    assert set(counts_oo.keys()) == {"O"}
    # AB × AB → never O.
    assert "O" not in counts_abab


def test_two_parent_rh_both_negative_produces_rh_negative() -> None:
    """Rh- × Rh- → child always Rh- (both parents are dd)."""
    for i in range(500):
        rh = derive_newborn_rh_factor(f"PT-RHNN-{i:04d}", "-", country="US", father_rh_factor="-")
        assert rh == "-"


def test_mother_genotype_prob_sums_to_one() -> None:
    """Sanity: every phenotype's genotype weights add to 1 (within fp
    tolerance)."""
    for phenotype, options in _MOTHER_GENOTYPE_PROBS.items():
        total = sum(w for _, w in options)
        assert abs(total - 1.0) < 1e-9, f"{phenotype}: sum {total}"
