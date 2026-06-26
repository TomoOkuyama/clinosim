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
    A typo in any ``organism.antibiogram`` key would otherwise silently produce a
    no-op susceptibility (PR-90 class silent-no-op).
    """
    antibiotics = data.get("antibiotics") or {}
    valid_antibiotic_keys = set(antibiotics.keys())
    for organism_id, organism in (data.get("organisms") or {}).items():
        antibiogram = (organism or {}).get("antibiogram") or {}
        for abx_key in antibiogram.keys():
            if abx_key not in valid_antibiotic_keys:
                raise ValueError(
                    f"microbiology.yaml: organism {organism_id!r} antibiogram "
                    f"references unknown antibiotic key {abx_key!r}; expected "
                    f"one of {sorted(valid_antibiotic_keys)}"
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
        normalize_probabilities([float(org_dist[k]) for k in org_ids])
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
                    raise ValueError(
                        f"microbiology generate: antibiogram references unknown "
                        f"antibiotic key {abx_key!r}; expected one of "
                        f"{sorted(antibiotics.keys())}"
                    )
                probs = normalize_probabilities([float(x) for x in sir])
                interp = _SIR[int(rng.choice(len(_SIR), p=probs))]
                result.susceptibilities.append(
                    SusceptibilityResult(antibiotic_loinc=str(loinc), interpretation=interp)
                )
        results.append(result)
    return results
