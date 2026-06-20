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

from clinosim.simulator.seeding import derive_sub_seed
from clinosim.types import MicrobiologyResult, SusceptibilityResult

_REF = Path(__file__).parent / "reference_data" / "microbiology.yaml"
_MICRO_SEED_OFFSET = 770_077
_SIR = ("S", "I", "R")


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    if not _REF.exists():
        return {}
    with open(_REF) as f:
        return yaml.safe_load(f) or {}


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

    rng = np.random.default_rng(derive_sub_seed(master_seed, _MICRO_SEED_OFFSET, encounter_id))

    org_dist = disease.get("organisms") or {}
    org_ids = list(org_dist.keys())
    org_probs = np.array([float(org_dist[k]) for k in org_ids], dtype=float)
    if org_probs.sum() > 0:
        org_probs = org_probs / org_probs.sum()

    results: list[MicrobiologyResult] = []
    for culture in disease.get("cultures") or []:
        if rng.random() > float(culture.get("order_prob", 1.0)):
            continue
        spec_key = str(culture.get("specimen", ""))
        spec = specimens.get(spec_key, {})
        grows = bool(rng.random() < float(culture.get("growth_prob", 0.0)))
        reported = (
            collected_datetime + timedelta(days=int(rng.integers(2, 4)))
            if collected_datetime
            else None
        )
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
                    continue
                probs = np.array([float(x) for x in sir], dtype=float)
                if probs.sum() > 0:
                    probs = probs / probs.sum()
                interp = _SIR[int(rng.choice(len(_SIR), p=probs))]
                result.susceptibilities.append(
                    SusceptibilityResult(antibiotic_loinc=str(loinc), interpretation=interp)
                )
        results.append(result)
    return results
