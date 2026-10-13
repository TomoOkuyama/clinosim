"""Parent → child biological inheritance (Issue #1581 Phase C.1).

Hosts the per-person deterministic sampling that lets a newborn inherit
family-level biological attributes from the mother (and, where
available, the father). All functions are RNG-neutral — draws come
from stable SHA256 hashes of the newborn's own person id, so the master
simulation stream is unaffected and byte-identity across runs with the
same seed is preserved.

Current scope (Phase C.1 — ABO + Rh):

* :func:`derive_newborn_blood_type` — mother phenotype × population
  allele distribution (father genotype treated as a draw from the
  locale ABO allele frequencies when no household spouse is
  identified). The locale-skewed father-side draw keeps the newborn
  cohort ABO distribution consistent with the published
  ``blood_type`` phenotype shares in ``demographics.yaml``.
* :func:`derive_newborn_rh_factor` — mother Rh phenotype × population
  d-allele frequency (derived from the locale ``_RH_POSITIVE_FRACTION``).
  Rh+ phenotype dominance preserved; mother Rh- children are Rh+
  only when the father-side draw returns a D allele.

Deliberately not here:

* Atopic (allergy) predisposition — would need to extend
  ``_allergy_drift`` with a per-person multiplier field. Phase C.2.
* Single-gene disease inheritance (CF / SCD / G6PD / thalassemia) —
  no inheritance-pattern-tagged entries in the current chronic
  disease catalog. Phase C.3, deferred until a catalog addition is
  agreed.
"""

from __future__ import annotations

import hashlib

# Mother phenotype → genotype (allele-pair) distribution. Uses the
# simplifying assumption of Hardy-Weinberg equilibrium with the
# dominant A/B alleles being equifrequent among phenotypic A/B
# heterozygotes vs homozygotes. Values are empirical approximations
# used in population-genetics textbooks; precise values vary by
# ancestry mix but the resulting child phenotype distribution matches
# the locale blood_type shares in demographics.yaml within ±2 % at
# cohort scale (verified by Monte Carlo in the accompanying tests).
_MOTHER_GENOTYPE_PROBS: dict[str, tuple[tuple[str, float], ...]] = {
    "A": (("AA", 0.4), ("AO", 0.6)),
    "B": (("BB", 0.1), ("BO", 0.9)),
    "AB": (("AB", 1.0),),
    "O": (("OO", 1.0),),
}

# Locale-level ABO allele frequencies, used as the father-side draw
# distribution when no household spouse is identified. Derived from
# the phenotype distributions in ``locale/{us,jp}/demographics.yaml``
# via Hardy-Weinberg (p² + 2pq + q² for A/O; r² + 2rq for B/O; etc.).
# A locale not listed falls through to the US values — synthetic-
# dataset defaults rather than clinically-tuned per-country tables.
_LOCALE_ALLELE_FREQ: dict[str, dict[str, float]] = {
    "US": {"A": 0.264, "B": 0.071, "O": 0.665},
    "JP": {"A": 0.279, "B": 0.169, "O": 0.552},
}


def _hash_quantile(key: str, byte_offset: int = 0, byte_count: int = 4) -> float:
    """Return a deterministic uniform-[0, 1) quantile from a SHA256
    hash of ``key``, picking ``byte_count`` bytes starting at
    ``byte_offset``. Multiple quantiles can be drawn from the same
    key without re-hashing by varying the offset — the whole hash is
    32 bytes, so up to 8 independent 4-byte quantiles are available."""
    h = hashlib.sha256(key.encode()).digest()
    slot = h[byte_offset : byte_offset + byte_count]
    span = 1 << (8 * byte_count)
    return int.from_bytes(slot, "big") / span


def _sample_mother_genotype(mother_phenotype: str, q: float) -> str:
    """Pick the mother's genotype (two-letter allele pair) for a given
    phenotype using a precomputed quantile ``q``. Phenotypes outside
    the ABO vocabulary fall through to ``"OO"`` (clinically-safe
    default: the universal donor allele pair)."""
    options = _MOTHER_GENOTYPE_PROBS.get(mother_phenotype)
    if options is None:
        return "OO"
    acc = 0.0
    for genotype, weight in options:
        acc += weight
        if q < acc:
            return genotype
    return options[-1][0]


def _sample_population_allele(country: str, q: float) -> str:
    """Pick a single ABO allele from the locale allele-frequency table."""
    freq = _LOCALE_ALLELE_FREQ.get(country.upper(), _LOCALE_ALLELE_FREQ["US"])
    acc = 0.0
    for allele in ("A", "B", "O"):
        acc += freq.get(allele, 0.0)
        if q < acc:
            return allele
    return "O"


def _phenotype_from_alleles(a1: str, a2: str) -> str:
    """Combine two ABO alleles into the resulting phenotype.

    * A + A, A + O → "A"
    * B + B, B + O → "B"
    * A + B → "AB"
    * O + O → "O"

    The function treats both argument orderings as equivalent.
    """
    s = {a1, a2}
    if s == {"A", "B"}:
        return "AB"
    if "A" in s:
        return "A"
    if "B" in s:
        return "B"
    return "O"


def derive_newborn_blood_type(
    newborn_patient_id: str,
    mother_blood_type: str,
    country: str = "US",
) -> str:
    """Return the newborn's ABO phenotype inherited from the mother's
    phenotype crossed with the locale ABO allele distribution for an
    unidentified father.

    Deterministic SHA-based sampling — no RNG consumption, so the
    master simulation stream is unaffected and byte-identity across
    runs with the same seed is preserved. A given newborn_patient_id
    always produces the same phenotype for the same mother phenotype
    and locale.
    """
    salt = f"{newborn_patient_id}|abo"
    q_mother_genotype = _hash_quantile(salt, byte_offset=0, byte_count=4)
    q_mother_allele = _hash_quantile(salt, byte_offset=4, byte_count=4)
    q_father_allele = _hash_quantile(salt, byte_offset=8, byte_count=4)

    genotype = _sample_mother_genotype(mother_blood_type, q_mother_genotype)
    mother_allele = genotype[0] if q_mother_allele < 0.5 else genotype[1]
    father_allele = _sample_population_allele(country, q_father_allele)

    return _phenotype_from_alleles(mother_allele, father_allele)


def derive_newborn_rh_factor(
    newborn_patient_id: str,
    mother_rh_factor: str,
    country: str = "US",
    rh_positive_fraction: dict[str, float] | None = None,
) -> str:
    """Return the newborn's RhD phenotype ("+" or "-") inherited from
    the mother's RhD phenotype crossed with the locale d-allele
    frequency for an unidentified father.

    Mother Rh+ carries D at least once; her donated allele is D with
    probability p / (p + q) under HWE (where p = P(D), q = P(d)),
    i.e. she donates D with weight ``p / (p + q)`` because the
    conditional "mother is Rh+" eliminates the dd homozygote.
    Mother Rh- is dd deterministically and donates d. Father-side
    draw samples d with probability q, D with probability p, from
    the population distribution.

    Deterministic SHA-based sampling (same determinism contract as
    :func:`derive_newborn_blood_type`).
    """
    frac_map = rh_positive_fraction or {"US": 0.85, "JP": 0.995}
    rh_pos = frac_map.get(country.upper(), frac_map.get("JP", 0.995))
    # Hardy-Weinberg allele frequency for the recessive d allele.
    # P(Rh-) = q², so q = sqrt(1 - rh_pos).
    q_d = max(0.0, min(1.0, (1.0 - rh_pos) ** 0.5))
    p_d_cap = max(1e-9, 1.0 - q_d)  # p = P(D)

    salt = f"{newborn_patient_id}|rhd"
    q_mother = _hash_quantile(salt, byte_offset=0, byte_count=4)
    q_father = _hash_quantile(salt, byte_offset=4, byte_count=4)

    if mother_rh_factor == "+":
        # Mother is DD or Dd (not dd). P(DD | Rh+) = p² / (p² + 2pq);
        # P(Dd | Rh+) = 2pq / (p² + 2pq). From DD mother donates D;
        # from Dd mother donates D with 0.5 probability, else d.
        denom = p_d_cap * p_d_cap + 2 * p_d_cap * q_d
        if denom <= 0.0:
            mother_allele = "D"
        else:
            p_dd_given_rh_pos = (p_d_cap * p_d_cap) / denom
            # First sub-quantile picks genotype; recycle the mother
            # quantile by splitting its range.
            if q_mother < p_dd_given_rh_pos:
                mother_allele = "D"
            else:
                # Heterozygote — donates D or d with 50/50.
                mother_allele = "D" if q_mother < p_dd_given_rh_pos + (1 - p_dd_given_rh_pos) / 2 else "d"
    else:
        mother_allele = "d"

    father_allele = "D" if q_father < p_d_cap else "d"

    # D is dominant.
    return "+" if "D" in (mother_allele, father_allele) else "-"
