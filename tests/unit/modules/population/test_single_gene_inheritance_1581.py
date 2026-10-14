"""Issue #1581 Phase C.3 — single-gene disease inheritance.

Autosomal recessive sampling + Mendelian Punnett for parent → child
phenotype propagation. Deterministic SHA-based sampling, so same
input tuples produce the same output across runs.
"""

from __future__ import annotations

from collections import Counter

from clinosim.modules.population.single_gene_inheritance import (
    _recessive_allele_freq,
    derive_initial_carrier_status,
    inherit_single_gene_autosomal_recessive,
)

_CF_CFG = {
    "display": "Cystic fibrosis",
    "inheritance_pattern": "autosomal_recessive",
    "carrier_frequency_by_race": {
        "white": 0.04,
        "black": 0.016,
        "asian": 0.011,
        "default": 0.015,
    },
}


def test_hardy_weinberg_recessive_allele_frequency() -> None:
    """q = 1 - sqrt(1 - P(≥ 1 disease allele))."""
    # Carrier freq 4% → q ≈ 0.0202 (allele freq)
    assert abs(_recessive_allele_freq(0.04) - 0.0202) < 1e-3
    assert _recessive_allele_freq(0.0) == 0.0
    assert _recessive_allele_freq(1.0) == 1.0


def test_derive_initial_carrier_status_deterministic() -> None:
    """Same (person_id, race, disease) → same phenotype across calls."""
    first = derive_initial_carrier_status("PT-SGD-1", "white", "E84", _CF_CFG)
    second = derive_initial_carrier_status("PT-SGD-1", "white", "E84", _CF_CFG)
    assert first == second


def test_derive_initial_carrier_matches_hw_distribution() -> None:
    """A cohort sampled from the Hardy-Weinberg allele frequency
    should produce ``carrier_freq`` carrier+affected prevalence and
    ``q²`` affected prevalence (within Monte-Carlo tolerance)."""
    affected = 0
    carrier = 0
    normal = 0
    trials = 5000
    for i in range(trials):
        phen = derive_initial_carrier_status(f"PT-HW-{i:04d}", "white", "E84", _CF_CFG)
        if phen == "affected":
            affected += 1
        elif phen == "carrier":
            carrier += 1
        else:
            normal += 1
    carrier_rate = (carrier + affected) / trials
    affected_rate = affected / trials
    # Target carrier_freq = 0.04, affected q² ≈ 0.0002.
    assert 0.02 < carrier_rate < 0.06, f"carrier+affected rate {carrier_rate:.4f} outside Hardy-Weinberg band"
    # Affected rate is tiny (q² ≈ 0.0002 → ~1/5000 trials) so just
    # confirm it's non-negative and bounded.
    assert 0 <= affected_rate < 0.01


def test_initial_sampling_respects_race_table() -> None:
    """Carrier rates should differ by race per the yaml."""
    # White 4% vs Asian 1.1% — compare carrier+affected counts.

    def race_rate(race: str, trials: int = 3000) -> float:
        hits = 0
        for i in range(trials):
            phen = derive_initial_carrier_status(f"PT-RACE-{race}-{i:04d}", race, "E84", _CF_CFG)
            if phen in ("carrier", "affected"):
                hits += 1
        return hits / trials

    r_white = race_rate("white")
    r_asian = race_rate("asian")
    # White strictly > Asian — carrier_frequency_by_race is 0.04 vs 0.011.
    assert r_white > r_asian, f"white {r_white:.3f} vs asian {r_asian:.3f} — race-conditioning not applied"


def test_inherit_two_carrier_parents_produces_mix() -> None:
    """Two carrier parents → 1/4 normal, 1/2 carrier, 1/4 affected
    across a cohort. Monte-Carlo band loose."""
    counts: Counter[str] = Counter()
    for i in range(1000):
        child = inherit_single_gene_autosomal_recessive(f"PT-INH-C-{i:04d}", "E84", "carrier", "carrier")
        counts[child] += 1
    total = sum(counts.values())
    # Expected: 25% normal, 50% carrier, 25% affected. Allow ±5%.
    assert 0.20 < counts["normal"] / total < 0.30, counts
    assert 0.45 < counts["carrier"] / total < 0.55, counts
    assert 0.20 < counts["affected"] / total < 0.30, counts


def test_inherit_two_normal_parents_always_normal() -> None:
    """Two normal (00) parents cannot produce a disease allele."""
    for i in range(200):
        child = inherit_single_gene_autosomal_recessive(f"PT-INH-N-{i:04d}", "E84", "normal", "normal")
        assert child == "normal"


def test_inherit_two_affected_parents_always_affected() -> None:
    """Two affected (11) parents can only produce a homozygous child."""
    for i in range(200):
        child = inherit_single_gene_autosomal_recessive(f"PT-INH-A-{i:04d}", "E84", "affected", "affected")
        assert child == "affected"


def test_inherit_carrier_and_normal_produces_normal_or_carrier() -> None:
    """1 carrier + 1 normal → 50% normal, 50% carrier (no affected)."""
    counts: Counter[str] = Counter()
    for i in range(500):
        child = inherit_single_gene_autosomal_recessive(f"PT-INH-CN-{i:04d}", "E84", "carrier", "normal")
        counts[child] += 1
    assert counts.get("affected", 0) == 0
    assert 0.40 < counts["carrier"] / 500 < 0.60
    assert 0.40 < counts["normal"] / 500 < 0.60


def test_inherit_deterministic_per_tuple() -> None:
    """Same (newborn_id, disease, mother, father) → same child phenotype."""
    first = inherit_single_gene_autosomal_recessive("PT-DET-1", "E84", "carrier", "carrier")
    second = inherit_single_gene_autosomal_recessive("PT-DET-1", "E84", "carrier", "carrier")
    assert first == second


# ===========================================================================
# X-linked recessive (G6PD / hemophilia pattern)
# ===========================================================================

_G6PD_CFG = {
    "display": "G6PD deficiency",
    "inheritance_pattern": "x_linked_recessive",
    "carrier_frequency_by_race": {
        "black": 0.12,  # ~12 % African-American males affected
        "white": 0.005,
        "default": 0.03,
    },
}


def test_x_linked_initial_male_rate_matches_q() -> None:
    """P(affected male) = q directly (hemizygous)."""
    affected_m = 0
    trials = 3000
    for i in range(trials):
        phen = derive_initial_carrier_status(f"PT-M-G6PD-{i:04d}", "black", "D55.0", _G6PD_CFG, sex="M")
        if phen == "affected":
            affected_m += 1
    rate = affected_m / trials
    # Expected 12 %, allow ±3 % Monte-Carlo band.
    assert 0.09 < rate < 0.15, f"black male G6PD-affected rate {rate:.3f} outside expected 12% band"


def test_x_linked_initial_female_mostly_carrier_or_normal() -> None:
    """Female affected rate = q², female carrier rate = 2q(1-q).
    For q=0.12 (black), expected carrier ~21 %, affected ~1.4 %."""
    counts: Counter[str] = Counter()
    trials = 3000
    for i in range(trials):
        counts[derive_initial_carrier_status(f"PT-F-G6PD-{i:04d}", "black", "D55.0", _G6PD_CFG, sex="F")] += 1
    carrier_rate = counts["carrier"] / trials
    affected_rate = counts["affected"] / trials
    # q=0.12 → carrier 2*0.12*0.88 = 0.2112, affected 0.0144.
    assert 0.17 < carrier_rate < 0.26, f"female carrier rate {carrier_rate:.3f}"
    assert 0.005 < affected_rate < 0.03, f"female affected rate {affected_rate:.3f}"


def test_x_linked_inherit_carrier_mother_normal_father_son_affected_rate() -> None:
    """Mother carrier (Xx), father normal (XY). Sons: 50 % affected,
    50 % normal. Daughters: 50 % carrier, 50 % normal (no affected)."""
    sons_affected = 0
    daughters_affected = 0
    trials = 1000
    for i in range(trials):
        from clinosim.modules.population.single_gene_inheritance import inherit_x_linked_recessive

        if inherit_x_linked_recessive(f"PT-SON-{i:04d}", "D55.0", "M", "carrier", "normal") == "affected":
            sons_affected += 1
        if inherit_x_linked_recessive(f"PT-DAU-{i:04d}", "D55.0", "F", "carrier", "normal") == "affected":
            daughters_affected += 1
    son_rate = sons_affected / trials
    assert 0.44 < son_rate < 0.56, f"son affected rate {son_rate:.3f} outside 50% band"
    assert daughters_affected == 0, f"carrier mother × normal father → daughter affected {daughters_affected}×"


def test_x_linked_affected_father_normal_mother_all_daughters_carriers() -> None:
    """Affected father (xY), normal mother (XX). Daughters all
    carriers (inherit father's x + mother's X). Sons all normal."""
    from clinosim.modules.population.single_gene_inheritance import inherit_x_linked_recessive

    for i in range(200):
        assert inherit_x_linked_recessive(f"PT-DAU-F-{i:04d}", "D55.0", "F", "normal", "affected") == "carrier"
        assert inherit_x_linked_recessive(f"PT-SON-F-{i:04d}", "D55.0", "M", "normal", "affected") == "normal"


def test_hemophilia_a_catalog_entry_loads() -> None:
    """Hemophilia A (D66) is in the single-gene catalog with the
    X-linked recessive pattern and reuses the same inheritance code
    path as G6PD — no new logic required."""
    from clinosim.locale.loader import load_single_gene_diseases

    catalog = (load_single_gene_diseases() or {}).get("single_gene_diseases") or {}
    assert "D66" in catalog, "Hemophilia A (D66) missing from single-gene catalog"
    cfg = catalog["D66"]
    assert cfg["inheritance_pattern"] == "x_linked_recessive"
    # Clinical basis: WFH 2024 ~1/5000 male incidence globally.
    freq = cfg["carrier_frequency_by_race"]["default"]
    assert 0.0001 < freq < 0.001


def test_hemophilia_b_catalog_entry_loads_and_rarer_than_a() -> None:
    """Hemophilia B (D67, Christmas disease) uses the same X-linked
    inheritance path. WFH 2024 reports ~1/25000 male incidence,
    which is 4-5x rarer than hemophilia A (~1/5000) — the catalog
    should reflect this ordering."""
    from clinosim.locale.loader import load_single_gene_diseases

    catalog = (load_single_gene_diseases() or {}).get("single_gene_diseases") or {}
    assert "D67" in catalog, "Hemophilia B (D67) missing from single-gene catalog"
    cfg_b = catalog["D67"]
    cfg_a = catalog["D66"]
    assert cfg_b["inheritance_pattern"] == "x_linked_recessive"
    freq_a = cfg_a["carrier_frequency_by_race"]["default"]
    freq_b = cfg_b["carrier_frequency_by_race"]["default"]
    assert freq_b < freq_a, f"hemophilia B freq {freq_b} should be < hemophilia A freq {freq_a}"
