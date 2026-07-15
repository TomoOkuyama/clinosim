"""Microbiology culture & susceptibility generation (AD-55 Base).

Reads ``reference_data/microbiology.yaml`` — all codes and probabilities are
data-driven (nothing hardcoded). Generation uses an encounter-scoped sub-seed so the
main simulation random stream (and golden files) is unperturbed (AD-16).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from clinosim.modules._shared import normalize_probabilities
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types import MicrobiologyResult, SusceptibilityResult

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_SIR = ("S", "I", "R")


def _validate_microbiology(data: dict[str, Any]) -> None:
    """Validate microbiology.yaml at load time — fail loud on orphan keys.

    Mirrors the validation pattern from ``clinosim.modules.hai.load_hai_antibiogram``.
    Covers the following cross-references (all silent-no-op risks):

    1. organism.antibiogram[abx_key] → antibiotics keys
    2. disease.organisms[org_id]    → organisms keys
    3. disease.cultures[i].specimen → specimens keys
    4. organism.snomed              → SNOMED system (non-empty string contract)
    5. specimen.snomed              → SNOMED system (non-empty string contract)
    6. specimen.test_loinc          → LOINC system (non-empty string contract)
    7. antibiotics[key] value       → LOINC system (non-empty string contract)
    """
    antibiotics = data.get("antibiotics") or {}
    organisms = data.get("organisms") or {}
    specimens = data.get("specimens") or {}
    diseases = data.get("diseases") or {}

    valid_antibiotic_keys = set(antibiotics.keys())
    valid_organism_keys = set(organisms.keys())
    valid_specimen_keys = set(specimens.keys())

    # Check antibiotic LOINC values are non-empty strings (#7)
    for abx_key, loinc in antibiotics.items():
        if not isinstance(loinc, str) or not loinc:
            raise ValueError(f"microbiology.yaml: antibiotic {abx_key!r} has invalid LOINC value {loinc!r}")

    # Check specimen.snomed + test_loinc are non-empty (#5 + #6)
    for spec_id, spec in specimens.items():
        if not isinstance(spec, dict):
            continue
        if not isinstance(spec.get("snomed"), str) or not spec["snomed"]:
            raise ValueError(f"microbiology.yaml: specimen {spec_id!r} has invalid SNOMED {spec.get('snomed')!r}")
        if not isinstance(spec.get("test_loinc"), str) or not spec["test_loinc"]:
            raise ValueError(
                f"microbiology.yaml: specimen {spec_id!r} has invalid test_loinc {spec.get('test_loinc')!r}"
            )

    for organism_id, organism in organisms.items():
        # Check organism.snomed non-empty (#4)
        if isinstance(organism, dict):
            if not isinstance(organism.get("snomed"), str) or not organism["snomed"]:
                raise ValueError(
                    f"microbiology.yaml: organism {organism_id!r} has invalid SNOMED {organism.get('snomed')!r}"
                )
        # Check organism.antibiogram keys → antibiotics (#1)
        antibiogram = (organism or {}).get("antibiogram") or {}
        for abx_key, triple in antibiogram.items():
            if abx_key not in valid_antibiotic_keys:
                raise ValueError(
                    f"microbiology.yaml: organism {organism_id!r} antibiogram "
                    f"references unknown antibiotic key {abx_key!r}; expected "
                    f"one of {sorted(valid_antibiotic_keys)}"
                )
            # Check SIR triple shape and sum (#8) — guards normalize_probabilities(fallback="raise")
            if not isinstance(triple, list) or len(triple) != 3:
                raise ValueError(
                    f"microbiology.yaml: organism {organism_id!r} antibiogram[{abx_key!r}] "
                    f"must be a 3-element [S, I, R] list, got {triple!r}"
                )
            if sum(float(x) for x in triple) <= 0:
                raise ValueError(
                    f"microbiology.yaml: organism {organism_id!r} antibiogram[{abx_key!r}] "
                    f"SIR triple sums to zero {triple!r}"
                )

    # Check disease.organisms keys → organisms set (#2)
    # and disease.cultures[i].specimen → specimens (#3)
    for disease_id, disease in diseases.items():
        if not isinstance(disease, dict):
            continue
        org_dict = disease.get("organisms")
        if org_dict is not None and not isinstance(org_dict, dict):
            raise ValueError(
                f"microbiology.yaml: disease {disease_id!r} 'organisms' must be a "
                f"mapping, got {type(org_dict).__name__!r}"
            )
        for org_id in (org_dict or {}).keys():
            if org_id not in valid_organism_keys:
                raise ValueError(
                    f"microbiology.yaml: disease {disease_id!r} references "
                    f"unknown organism {org_id!r}; expected one of "
                    f"{sorted(valid_organism_keys)}"
                )
        for culture in disease.get("cultures") or []:
            spec_key = culture.get("specimen") if isinstance(culture, dict) else None
            if spec_key and spec_key not in valid_specimen_keys:
                raise ValueError(
                    f"microbiology.yaml: disease {disease_id!r} culture references "
                    f"unknown specimen {spec_key!r}; expected one of "
                    f"{sorted(valid_specimen_keys)}"
                )


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    path = _REF_DIR / "microbiology.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    _validate_microbiology(data)
    return data


def antibiotic_loinc_lookup() -> dict[str, str]:
    """Return antibiotic_key -> LOINC map from the cached microbiology.yaml.

    Single source of truth for antibiotic LOINC codes, shared with
    ``modules/antibiotic`` (avoids a second cross-module raw YAML parse of the
    same file). Returns a fresh dict each call; the underlying YAML is cached
    and validated by ``_load`` / ``_validate_microbiology``.
    """
    return {str(k): str(v) for k, v in (_load().get("antibiotics") or {}).items()}


def has_microbiology(disease_id: str) -> bool:
    """Whether the disease has a microbiology profile (i.e. is a culture-relevant infection)."""
    return disease_id in (_load().get("diseases") or {})


def generate_microbiology(
    disease_id: str,
    collected_datetime: datetime | None,
    encounter_id: str,
    master_seed: int,
) -> list[MicrobiologyResult]:
    """Generate culture results (+ susceptibilities) for an infection encounter."""
    data = _load()
    disease = (data.get("diseases") or {}).get(disease_id)
    if not disease:
        return []

    specimens = data.get("specimens") or {}
    antibiotics = data.get("antibiotics") or {}
    organisms = data.get("organisms") or {}

    rng = np.random.default_rng(derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["microbiology"], encounter_id))

    org_dist = disease.get("organisms") or {}
    org_ids = list(org_dist.keys())
    org_probs = (
        normalize_probabilities([float(org_dist[k]) for k in org_ids], fallback="raise")
        if org_ids
        else np.array([], dtype=float)
    )

    results: list[MicrobiologyResult] = []
    for culture in disease.get("cultures") or []:
        if rng.random() > float(culture.get("order_prob", 1.0)):
            continue
        spec_key = str(culture.get("specimen", ""))
        spec = specimens.get(spec_key, {})
        grows = bool(rng.random() < float(culture.get("growth_prob", 0.0)))
        reported = collected_datetime + timedelta(days=int(rng.integers(2, 4))) if collected_datetime else None
        result = MicrobiologyResult(
            encounter_id=encounter_id,
            specimen=spec_key,
            specimen_snomed=str(spec.get("snomed", "")),
            test_loinc=str(spec.get("test_loinc", "")),
            collected_datetime=collected_datetime,
            reported_datetime=reported,
            growth=grows,
        )
        if grows and org_ids:
            org_id = str(rng.choice(org_ids, p=org_probs))
            org = organisms.get(org_id, {})
            result.organism_snomed = str(org.get("snomed", ""))
            result.quantitation = str(culture.get("quantitation", ""))
            for abx_key, sir in (org.get("antibiogram") or {}).items():
                loinc = antibiotics.get(abx_key)
                if not loinc:
                    raise ValueError(
                        f"microbiology generate: antibiotic key {abx_key!r} has null/empty "
                        f"LOINC value {loinc!r}; should have been caught at load time by "
                        f"_validate_microbiology"
                    )
                probs = normalize_probabilities([float(x) for x in sir], fallback="raise")
                interp = _SIR[int(rng.choice(len(_SIR), p=probs))]
                result.susceptibilities.append(SusceptibilityResult(antibiotic_loinc=str(loinc), interpretation=interp))
        results.append(result)
    return results
