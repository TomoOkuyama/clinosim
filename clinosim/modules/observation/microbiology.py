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
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clinosim import determinism
from clinosim.datafiles import load_data_yaml
from clinosim.modules._shared import normalize_probabilities
from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types import MicrobiologyResult, SusceptibilityResult

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_SIR = ("S", "I", "R")


def _non_empty_code(code: str, owner: str, what: str) -> str:
    if not code:
        raise ValueError(f"microbiology.yaml: {owner} has invalid {what} {code!r}")
    return code


class _Specimen(BaseModel):
    model_config = ConfigDict(extra="allow")

    snomed: str
    test_loinc: str

    @field_validator("snomed")
    @classmethod
    def _snomed(cls, code: str) -> str:
        return _non_empty_code(code, "specimen", "SNOMED")

    @field_validator("test_loinc")
    @classmethod
    def _test_loinc(cls, code: str) -> str:
        return _non_empty_code(code, "specimen", "test_loinc")


class _Organism(BaseModel):
    model_config = ConfigDict(extra="allow")

    snomed: str
    antibiogram: dict[str, list[float]] | None = None

    @field_validator("snomed")
    @classmethod
    def _snomed(cls, code: str) -> str:
        return _non_empty_code(code, "organism", "SNOMED")

    @field_validator("antibiogram")
    @classmethod
    def _sir_triples(cls, antibiogram: dict[str, list[float]] | None) -> dict[str, list[float]] | None:
        """Guards ``normalize_probabilities(fallback="raise")`` at generation time."""
        for abx_key, triple in (antibiogram or {}).items():
            if len(triple) != 3:
                raise ValueError(
                    f"microbiology.yaml: antibiogram[{abx_key!r}] must be a 3-element [S, I, R] list, got {triple!r}"
                )
            if sum(triple) <= 0:
                raise ValueError(f"microbiology.yaml: antibiogram[{abx_key!r}] SIR triple sums to zero {triple!r}")
        return antibiogram


class _Culture(BaseModel):
    model_config = ConfigDict(extra="allow")

    specimen: str | None = None


class _DiseaseProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    organisms: dict[str, Any] | None = None
    cultures: list[_Culture] | None = None

    @field_validator("organisms", mode="before")
    @classmethod
    def _organisms_mapping(cls, organisms: Any) -> Any:
        if organisms is not None and not isinstance(organisms, dict):
            raise ValueError(f"microbiology.yaml: 'organisms' must be a mapping, got {type(organisms).__name__!r}")
        return organisms


class MicrobiologyConfig(BaseModel):
    """Shape of microbiology.yaml. Every cross-reference is a silent-no-op
    risk, so each must resolve within the file (mirrors the HAI antibiogram
    loader): antibiogram keys → ``antibiotics``, disease organisms →
    ``organisms``, culture specimens → ``specimens``; codes are non-empty."""

    model_config = ConfigDict(extra="allow")

    antibiotics: dict[str, str] = Field(default_factory=dict)
    organisms: dict[str, _Organism] = Field(default_factory=dict)
    specimens: dict[str, _Specimen] = Field(default_factory=dict)
    diseases: dict[str, _DiseaseProfile] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _empty_sections_are_absent(cls, data: Any) -> Any:
        """A ``null`` section reads as an empty one, as the loader always did."""
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data

    @field_validator("antibiotics")
    @classmethod
    def _antibiotic_loincs(cls, antibiotics: dict[str, str]) -> dict[str, str]:
        for abx_key, loinc in antibiotics.items():
            _non_empty_code(loinc, f"antibiotic {abx_key!r}", "LOINC value")
        return antibiotics

    @model_validator(mode="after")
    def _references_resolve(self) -> MicrobiologyConfig:
        for organism_id, organism in self.organisms.items():
            for abx_key in organism.antibiogram or {}:
                if abx_key not in self.antibiotics:
                    raise ValueError(
                        f"microbiology.yaml: organism {organism_id!r} antibiogram "
                        f"references unknown antibiotic key {abx_key!r}; expected "
                        f"one of {sorted(self.antibiotics)}"
                    )
        for disease_id, disease in self.diseases.items():
            for org_id in disease.organisms or {}:
                if org_id not in self.organisms:
                    raise ValueError(
                        f"microbiology.yaml: disease {disease_id!r} references "
                        f"unknown organism {org_id!r}; expected one of {sorted(self.organisms)}"
                    )
            for culture in disease.cultures or []:
                if culture.specimen and culture.specimen not in self.specimens:
                    raise ValueError(
                        f"microbiology.yaml: disease {disease_id!r} culture references "
                        f"unknown specimen {culture.specimen!r}; expected one of {sorted(self.specimens)}"
                    )
        return self


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    path = _REF_DIR / "microbiology.yaml"
    if not path.exists():
        return {}
    data = load_data_yaml(path) or {}
    MicrobiologyConfig.model_validate(data)
    return data


def antibiotic_loinc_lookup() -> dict[str, str]:
    """Return antibiotic_key -> LOINC map from the cached microbiology.yaml.

    Single source of truth for antibiotic LOINC codes, shared with
    ``modules/antibiotic`` (avoids a second cross-module raw YAML parse of the
    same file). Returns a fresh dict each call; the underlying YAML is cached
    and validated by ``_load`` / ``MicrobiologyConfig``.
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

    rng = determinism.default_rng(derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["microbiology"], encounter_id))

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
                        f"MicrobiologyConfig"
                    )
                probs = normalize_probabilities([float(x) for x in sir], fallback="raise")
                interp = _SIR[int(rng.choice(len(_SIR), p=probs))]
                result.susceptibilities.append(SusceptibilityResult(antibiotic_loinc=str(loinc), interpretation=interp))
        results.append(result)
    return results
