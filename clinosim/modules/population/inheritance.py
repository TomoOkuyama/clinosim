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
  d-allele frequency (derived from the locale RhD-positive fraction,
  ``locale/<cc>/population_genetics.yaml``).
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

from clinosim.determinism import sha_quantile
from clinosim.locale.loader import load_population_genetics

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

# The locale ABO allele frequencies (father-side draw when no household
# spouse is identified) and the RhD-positive fraction are country data:
# ``locale/<cc>/population_genetics.yaml`` (Issue #3142).


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
    freq = load_population_genetics(country).abo_allele_frequencies
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
    father_blood_type: str | None = None,
) -> str:
    """Return the newborn's ABO phenotype inherited from the mother's
    phenotype crossed with the father's phenotype when a household
    father is identified (Phase C.2 extension), otherwise falls
    through to the locale ABO allele distribution for an
    unidentified father.

    Both parents' genotypes are inferred from phenotype under
    Hardy-Weinberg equilibrium with the standard A/B allele-pair
    distribution. Each parent donates one of their two alleles with
    50/50 weight (biologically-correct Punnett).

    Deterministic SHA-based sampling — no RNG consumption, so the
    master simulation stream is unaffected and byte-identity across
    runs with the same seed is preserved. A given newborn_patient_id
    always produces the same phenotype for the same (mother, father,
    locale) tuple.
    """
    salt = f"{newborn_patient_id}|abo"
    q_mother_genotype = sha_quantile(salt, byte_offset=0, byte_count=4)
    q_mother_allele = sha_quantile(salt, byte_offset=4, byte_count=4)
    q_father_source = sha_quantile(salt, byte_offset=8, byte_count=4)
    q_father_allele = sha_quantile(salt, byte_offset=12, byte_count=4)

    mother_genotype = _sample_mother_genotype(mother_blood_type, q_mother_genotype)
    mother_allele = mother_genotype[0] if q_mother_allele < 0.5 else mother_genotype[1]

    if father_blood_type:
        father_genotype = _sample_mother_genotype(father_blood_type, q_father_source)
        father_allele = father_genotype[0] if q_father_allele < 0.5 else father_genotype[1]
    else:
        father_allele = _sample_population_allele(country, q_father_allele)

    return _phenotype_from_alleles(mother_allele, father_allele)


def _parent_rh_allele(
    phenotype: str,
    q_genotype: float,
    q_allele: float,
    p_d: float,
    q_d: float,
) -> str:
    """Draw a parent's donated RhD allele from their phenotype under HWE.

    Rh+ carries D ≥ once: P(DD | Rh+) = p² / (p² + 2pq); P(Dd | Rh+) =
    2pq / (p² + 2pq). From DD donates D; from Dd donates D or d with
    50/50. Rh- is dd and donates d deterministically.
    """
    if phenotype == "+":
        denom = p_d * p_d + 2 * p_d * q_d
        if denom <= 0.0:
            return "D"
        p_dd_given_rh_pos = (p_d * p_d) / denom
        if q_genotype < p_dd_given_rh_pos:
            return "D"
        return "D" if q_allele < 0.5 else "d"
    return "d"


def derive_newborn_rh_factor(
    newborn_patient_id: str,
    mother_rh_factor: str,
    country: str = "US",
    father_rh_factor: str | None = None,
) -> str:
    """Return the newborn's RhD phenotype ("+" or "-") inherited from
    the mother's RhD phenotype crossed with the father's phenotype
    when a household father is identified (Phase C.2 extension),
    otherwise falls through to the locale d-allele frequency for an
    unidentified father.

    Deterministic SHA-based sampling (same determinism contract as
    :func:`derive_newborn_blood_type`).
    """
    rh_pos = load_population_genetics(country).rh_positive_fraction
    # Hardy-Weinberg allele frequency for the recessive d allele.
    # P(Rh-) = q², so q = sqrt(1 - rh_pos).
    q_d = max(0.0, min(1.0, (1.0 - rh_pos) ** 0.5))
    p_d = max(1e-9, 1.0 - q_d)

    salt = f"{newborn_patient_id}|rhd"
    q_mother_genotype = sha_quantile(salt, byte_offset=0, byte_count=4)
    q_mother_allele = sha_quantile(salt, byte_offset=4, byte_count=4)
    q_father_source = sha_quantile(salt, byte_offset=8, byte_count=4)
    q_father_allele = sha_quantile(salt, byte_offset=12, byte_count=4)

    mother_allele = _parent_rh_allele(mother_rh_factor, q_mother_genotype, q_mother_allele, p_d, q_d)
    if father_rh_factor:
        father_allele = _parent_rh_allele(father_rh_factor, q_father_source, q_father_allele, p_d, q_d)
    else:
        father_allele = "D" if q_father_source < p_d else "d"

    # D is dominant.
    return "+" if "D" in (mother_allele, father_allele) else "-"
