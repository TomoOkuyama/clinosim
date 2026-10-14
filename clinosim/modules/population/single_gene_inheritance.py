"""Single-gene disease inheritance (Issue #1581 Phase C.3).

Supports autosomal recessive (CF / SCD) and X-linked recessive
(G6PD / hemophilia-like).

Phenotype representation on ``PersonRecord.carrier_status[icd]``:

  "normal"   — no disease allele (homozygous reference or male
               unaffected XY)
  "carrier"  — heterozygous (asymptomatic for autosomal recessive
               conditions; female Xx for X-linked)
  "affected" — homozygous (autosomal) or hemizygous male (X-linked)
               or homozygous-affected female (X-linked xx)

For X-linked, the ``carrier_frequency_by_race`` entry in the yaml
is interpreted as the X-chromosome mutant-allele frequency ``q``
(equals P(affected male) directly), not the female-carrier rate.

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
    sex: str = "",
) -> str:
    """Sample a person's initial carrier status for one single-gene
    disease at cohort-generation time.

    Autosomal recessive: two independent allele draws using the Hardy-
    Weinberg allele frequency q = 1 - sqrt(1 - carrier_freq). Phenotype
    = "normal" if both reference, "carrier" if one disease allele,
    "affected" if two disease alleles.

    X-linked recessive: uses the yaml ``carrier_frequency_by_race``
    value as the X-chromosome mutant-allele frequency ``q`` directly
    (equals P(affected male)). Males (one X) are "affected" when
    their single draw < q, else "normal". Females (two X) sample
    two independent X alleles — both=1 → "affected", one=1 →
    "carrier", none → "normal".

    Deterministic SHA-based sampling (RNG-neutral) so this layer can
    be added without shifting any existing master stream.
    """
    pattern = str(disease_cfg.get("inheritance_pattern", ""))
    salt = f"{person_id}|single_gene|{disease_code}|v1"

    if pattern == "autosomal_recessive":
        carrier_freq = _carrier_freq_for_race(disease_cfg, race)
        q = _recessive_allele_freq(carrier_freq)
        if q <= 0.0:
            return "normal"
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

    if pattern == "x_linked_recessive":
        # yaml value is X-allele mutant frequency q directly.
        q = max(0.0, min(1.0, _carrier_freq_for_race(disease_cfg, race)))
        if q <= 0.0:
            return "normal"
        if sex == "M":
            q_x = _hash_quantile(salt, byte_offset=0, byte_count=4)
            return "affected" if q_x < q else "normal"
        if sex == "F":
            q_x1 = _hash_quantile(salt, byte_offset=0, byte_count=4)
            q_x2 = _hash_quantile(salt, byte_offset=4, byte_count=4)
            x1 = 1 if q_x1 < q else 0
            x2 = 1 if q_x2 < q else 0
            total = x1 + x2
            if total == 0:
                return "normal"
            if total == 1:
                return "carrier"
            return "affected"
        return "normal"

    return "normal"


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


def inherit_x_linked_recessive(
    newborn_patient_id: str,
    disease_code: str,
    child_sex: str,
    mother_phenotype: str,
    father_phenotype: str,
) -> str:
    """Compute the newborn's phenotype for an X-linked recessive
    disease given mother and father phenotypes and the child's sex.

    Rules:
    * Mother donates ONE X.
      - "normal" (XX reference) → donates 0.
      - "carrier" (Xx) → donates 0 or 1 with 50/50.
      - "affected" (xx) → donates 1.
    * Father donates X ONLY to a daughter (sons get Y from father).
      - "normal" (XY reference) → donates 0 X.
      - "affected" (xY) → donates 1 X.
    * Child sex "M": phenotype = "affected" if mother-X=1, else "normal".
    * Child sex "F": phenotype derived from both parent X donations
      (one from each) via the same homo/hetero/none rule as autosomal.

    Unknown sex falls back to the female path (conservative — may
    over-count carrier females, but X-linked disorders are typically
    scored on sex).
    """
    salt = f"{newborn_patient_id}|single_gene_inherit_x|{disease_code}|v1"
    q_mother = _hash_quantile(salt, byte_offset=0, byte_count=4)

    # Mother-donated X.
    if (mother_phenotype or "normal") == "normal":
        mother_x = 0
    elif mother_phenotype == "carrier":
        mother_x = 1 if q_mother < 0.5 else 0
    else:  # "affected"
        mother_x = 1

    if child_sex == "M":
        return "affected" if mother_x == 1 else "normal"

    # Female path — need father-donated X.
    father_x = 1 if (father_phenotype or "normal") == "affected" else 0
    total = mother_x + father_x
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
    sex = getattr(person, "sex", "") or ""
    person_id = getattr(person, "person_id", "")
    affected: list[str] = []
    for code, disease_cfg in (catalog or {}).items():
        phenotype = derive_initial_carrier_status(person_id, race, code, disease_cfg or {}, sex=sex)
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
    child_sex = getattr(newborn, "sex", "") or ""
    for code, disease_cfg in (catalog or {}).items():
        pattern = str((disease_cfg or {}).get("inheritance_pattern", ""))
        mother_phen = getattr(mother, "carrier_status", {}).get(code, "normal")
        father_phen = "normal"
        if father is not None:
            father_phen = getattr(father, "carrier_status", {}).get(code, "normal")

        if pattern == "autosomal_recessive":
            child_phen = inherit_single_gene_autosomal_recessive(
                newborn_patient_id,
                code,
                mother_phen,
                father_phen,
            )
        elif pattern == "x_linked_recessive":
            child_phen = inherit_x_linked_recessive(
                newborn_patient_id,
                code,
                child_sex,
                mother_phen,
                father_phen,
            )
        else:
            child_phen = "normal"

        newborn.carrier_status[code] = child_phen
        if child_phen == "affected":
            affected.append(code)
    return affected
