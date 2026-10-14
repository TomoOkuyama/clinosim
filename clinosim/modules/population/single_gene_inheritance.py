"""Single-gene disease inheritance (Issue #1581 Phase C.3).

Supports autosomal recessive (CF / SCD-like) in this slice; the
X-linked branch (G6PD / hemophilia) is a planned follow-up with its
own sex-conditional Punnett.

Phenotype representation on ``PersonRecord.carrier_status[icd]``:

  "normal"   — no disease allele (homozygous reference)
  "carrier"  — heterozygous (asymptomatic for recessive conditions)
  "affected" — homozygous (autosomal) or hemizygous male (X-linked)

All sampling is deterministic SHA-based so the master simulation
stream is unaffected and byte-identity across runs is preserved.
"""

from __future__ import annotations

import hashlib
from typing import Any


def _hash_quantile(key: str, byte_offset: int = 0, byte_count: int = 4) -> float:
    """Return a deterministic uniform-[0, 1) quantile from a SHA256
    hash of ``key``. Mirrors the pattern in ``inheritance.py`` so a
    single hash can serve multiple draws by varying the offset."""
    h = hashlib.sha256(key.encode()).digest()
    slot = h[byte_offset : byte_offset + byte_count]
    span = 1 << (8 * byte_count)
    return int.from_bytes(slot, "big") / span


def _carrier_freq_for_race(disease_cfg: dict, race: str) -> float:
    """Pick the race-conditional carrier frequency from the yaml,
    falling back to ``default`` when the race is unknown or empty
    (JP locale without a race_distribution)."""
    table = disease_cfg.get("carrier_frequency_by_race") or {}
    if race and race in table:
        return float(table[race])
    return float(table.get("default", 0.0))


def _recessive_allele_freq(carrier_freq: float) -> float:
    """Hardy-Weinberg: given P(≥ 1 disease allele) = carrier_freq
    = 2pq + q² ≈ 2q for small q, invert to allele frequency.

    Precise: solve q² + 2q(1-q) = carrier_freq → q = 1 - sqrt(1 -
    carrier_freq). Clamped to [0, 1].
    """
    cf = max(0.0, min(1.0, float(carrier_freq)))
    if cf <= 0.0:
        return 0.0
    return 1.0 - (1.0 - cf) ** 0.5


def derive_initial_carrier_status(
    person_id: str,
    race: str,
    disease_code: str,
    disease_cfg: dict,
) -> str:
    """Sample a person's initial carrier status for one single-gene
    disease at cohort-generation time.

    Autosomal recessive: two independent allele draws using the Hardy-
    Weinberg allele frequency q = 1 - sqrt(1 - carrier_freq). Phenotype
    = "normal" if both reference, "carrier" if one disease allele,
    "affected" if two disease alleles.

    X-linked recessive: NOT YET IMPLEMENTED — see the planned follow-
    up for G6PD / hemophilia. Returns ``"normal"`` conservatively.

    Deterministic SHA-based sampling (RNG-neutral) so this layer can
    be added without shifting any existing master stream.
    """
    pattern = str(disease_cfg.get("inheritance_pattern", ""))
    if pattern != "autosomal_recessive":
        return "normal"

    carrier_freq = _carrier_freq_for_race(disease_cfg, race)
    q = _recessive_allele_freq(carrier_freq)
    if q <= 0.0:
        return "normal"

    salt = f"{person_id}|single_gene|{disease_code}|v1"
    q_allele_a = _hash_quantile(salt, byte_offset=0, byte_count=4)
    q_allele_b = _hash_quantile(salt, byte_offset=4, byte_count=4)
    allele_a = 1 if q_allele_a < q else 0
    allele_b = 1 if q_allele_b < q else 0
    total = allele_a + allele_b
    if total == 0:
        return "normal"
    if total == 1:
        return "carrier"
    return "affected"


def _sample_parent_donated_allele(parent_phenotype: str, quantile: float) -> int:
    """Given a parent's phenotype and a deterministic uniform
    quantile, return the allele (0 = reference, 1 = disease) the
    parent donates to a child under Mendelian autosomal-recessive
    inheritance."""
    if parent_phenotype == "normal":
        return 0
    if parent_phenotype == "affected":
        return 1
    # Carrier (heterozygous) — 50/50 donation.
    return 1 if quantile < 0.5 else 0


def inherit_single_gene_autosomal_recessive(
    newborn_patient_id: str,
    disease_code: str,
    mother_phenotype: str,
    father_phenotype: str,
) -> str:
    """Compute the newborn's phenotype for one single-gene autosomal-
    recessive disease given both parent phenotypes. Deterministic
    SHA-based Punnett sampling: for each parent, derive one donated
    allele from their phenotype (``"carrier"`` splits 50/50).

    Returns one of ``"normal"`` / ``"carrier"`` / ``"affected"``.
    When a parent phenotype is empty / unknown (test fixtures or
    pre-#1581 cohorts), it is treated as ``"normal"`` so the child
    phenotype collapses to the other parent's donation.
    """
    salt = f"{newborn_patient_id}|single_gene_inherit|{disease_code}|v1"
    q_mother = _hash_quantile(salt, byte_offset=0, byte_count=4)
    q_father = _hash_quantile(salt, byte_offset=4, byte_count=4)

    mother_allele = _sample_parent_donated_allele(mother_phenotype or "normal", q_mother)
    father_allele = _sample_parent_donated_allele(father_phenotype or "normal", q_father)
    total = mother_allele + father_allele
    if total == 0:
        return "normal"
    if total == 1:
        return "carrier"
    return "affected"


def apply_initial_carrier_sampling(person: Any, catalog: dict[str, Any]) -> list[str]:
    """Walk every disease in the catalog and sample the person's
    initial carrier status, writing to ``person.carrier_status``.
    Returns the list of ICD codes for which the person is affected
    (so the caller can append them to ``person.chronic_conditions``).
    """
    race = getattr(person, "race", "") or ""
    person_id = getattr(person, "person_id", "")
    affected: list[str] = []
    for code, disease_cfg in (catalog or {}).items():
        phenotype = derive_initial_carrier_status(person_id, race, code, disease_cfg or {})
        person.carrier_status[code] = phenotype
        if phenotype == "affected":
            affected.append(code)
    return affected


def apply_newborn_inheritance(
    newborn: Any,
    mother: Any,
    father: Any | None,
    catalog: dict[str, Any],
) -> list[str]:
    """Walk every disease in the catalog and compute the newborn's
    phenotype from the parent phenotypes (Punnett). Writes
    ``newborn.carrier_status``. Returns ICD codes for which the
    newborn is affected (so the caller can append them to
    ``newborn.chronic_conditions`` and emit the condition).

    When the father is ``None`` (single-mother household or test
    fixture), the father phenotype collapses to ``"normal"`` for the
    purposes of the Punnett draw — a conservative default that may
    under-report affected incidence for diseases where the father
    is a carrier. A separate population-level sampling path for
    unknown fathers is a potential follow-up.
    """
    affected: list[str] = []
    newborn_patient_id = getattr(newborn, "person_id", "") or getattr(newborn, "patient_id", "")
    for code, disease_cfg in (catalog or {}).items():
        pattern = str((disease_cfg or {}).get("inheritance_pattern", ""))
        if pattern != "autosomal_recessive":
            # X-linked follow-up — leave as "normal" for now.
            newborn.carrier_status[code] = "normal"
            continue
        mother_phen = getattr(mother, "carrier_status", {}).get(code, "normal")
        father_phen = "normal"
        if father is not None:
            father_phen = getattr(father, "carrier_status", {}).get(code, "normal")
        child_phen = inherit_single_gene_autosomal_recessive(
            newborn_patient_id,
            code,
            mother_phen,
            father_phen,
        )
        newborn.carrier_status[code] = child_phen
        if child_phen == "affected":
            affected.append(code)
    return affected
