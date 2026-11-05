"""Microbiology culture & susceptibility generation (AD-55 Base).

Reads ``reference_data/microbiology.yaml`` — all codes and probabilities are
data-driven (nothing hardcoded). Generation uses an encounter-scoped sub-seed so the
main simulation random stream (and golden files) is unperturbed (AD-16).
"""

from __future__ import annotations

from collections.abc import Sequence
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
    culture_orders: list[str] = Field(default_factory=list)

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
    culture_order_match_window_hours: float = 6.0
    repeat_culture_persistence_prob: float = Field(default=0.0, ge=0.0, le=1.0)
    workup_culture_window_hours: float = 24.0
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


def culture_order_names(specimen: str) -> frozenset[str]:
    """Canonical lab-order names that request a culture of ``specimen`` (Issue #2585)."""
    spec = (_load().get("specimens") or {}).get(specimen) or {}
    return frozenset(spec.get("culture_orders") or ())


def culture_order_match_window_hours() -> float:
    """How far a culture order may be from the culture's collection time (Issue #2585)."""
    return float(_load().get("culture_order_match_window_hours", 6.0))


def workup_culture_window_hours() -> float:
    """How soon after admission a protocol culture counts as the workup culture (Issue #2640)."""
    return float(_load().get("workup_culture_window_hours", 24.0))


def has_microbiology(disease_id: str) -> bool:
    """Whether the disease has a microbiology profile (i.e. is a culture-relevant infection)."""
    return disease_id in (_load().get("diseases") or {})


def specimen_for_order(display_name: str) -> str:
    """The specimen a lab order cultures (Issue #2640), or "" for any other order."""
    from clinosim.modules.observation.engine import canonical_lab_name

    canon = canonical_lab_name(display_name or "")
    for spec_key, spec in (_load().get("specimens") or {}).items():
        if canon in (spec.get("culture_orders") or ()):
            return str(spec_key)
    return ""


def workup_culture_order(specimen: str) -> str:
    """The order name the admission workup places for a ``specimen`` culture."""
    spec = (_load().get("specimens") or {}).get(specimen) or {}
    return str((spec.get("culture_orders") or [""])[0])


def culture_draws(orders: list[Any], encounter_id: str) -> list[tuple[str, datetime]]:
    """One (specimen, collection time) per culture draw among an encounter's
    orders (Issue #2640). Orders of one specimen placed at the same time are
    one draw (two blood-culture sets); cancelled orders draw nothing."""
    draws: set[tuple[str, datetime]] = set()
    for order in orders:
        get = order.get if isinstance(order, dict) else lambda k, d=None, o=order: getattr(o, k, d)
        if str(getattr(get("order_type"), "value", get("order_type"))) != "lab":
            continue
        if encounter_id and (get("encounter_id", "") or "") not in ("", encounter_id):
            continue
        if str(getattr(get("status"), "value", get("status"))) == "cancelled":
            continue
        spec = specimen_for_order(str(get("display_name", "") or ""))
        when = get("ordered_datetime")
        if spec and isinstance(when, datetime):
            draws.add((spec, when))
    return sorted(draws, key=lambda d: (d[1], d[0]))


def workup_culture_specimens(disease_id: str, encounter_id: str, master_seed: int) -> list[str]:
    """The specimens the disease's admission workup cultures (``order_prob``)."""
    disease = (_load().get("diseases") or {}).get(disease_id) or {}
    rng = determinism.default_rng(
        derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["microbiology"], f"{encounter_id}:workup")
    )
    return [
        str(c.get("specimen", ""))
        for c in disease.get("cultures") or []
        if rng.random() <= float(c.get("order_prob", 1.0))
    ]


def culture_results(
    disease_id: str,
    draws: Sequence[tuple[str, datetime | None]],
    encounter_id: str,
    master_seed: int,
) -> list[MicrobiologyResult]:
    """One culture result per draw (Issue #2640).

    The first draw of a specimen the disease's profile cultures grows with
    the profile's ``growth_prob``; a later draw of that specimen grows the
    same organism again with ``repeat_culture_persistence_prob`` when an
    earlier one grew, and is no growth otherwise. A specimen the profile does
    not culture (or a disease with no profile) is no growth.
    """
    data = _load()
    disease = (data.get("diseases") or {}).get(disease_id) or {}
    specimens = data.get("specimens") or {}
    antibiotics = data.get("antibiotics") or {}
    organisms = data.get("organisms") or {}
    persistence = float(data.get("repeat_culture_persistence_prob", 0.0))
    profile = {str(c.get("specimen", "")): c for c in disease.get("cultures") or []}

    org_dist = disease.get("organisms") or {}
    org_ids = list(org_dist.keys())
    org_probs = (
        normalize_probabilities([float(org_dist[k]) for k in org_ids], fallback="raise")
        if org_ids
        else np.array([], dtype=float)
    )

    results: list[MicrobiologyResult] = []
    first_of: dict[str, MicrobiologyResult] = {}
    for n, (spec_key, collected) in enumerate(draws):
        rng = determinism.default_rng(
            derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["microbiology"], f"{encounter_id}:{spec_key}:{n}")
        )
        spec = specimens.get(spec_key, {})
        culture = profile.get(spec_key)
        reported = collected + timedelta(days=int(rng.integers(2, 4))) if collected else None
        result = MicrobiologyResult(
            encounter_id=encounter_id,
            specimen=spec_key,
            specimen_snomed=str(spec.get("snomed", "")),
            test_loinc=str(spec.get("test_loinc", "")),
            collected_datetime=collected,
            reported_datetime=reported,
            growth=False,
        )
        earlier = first_of.get(spec_key)
        if earlier is not None:
            if earlier.growth and rng.random() < persistence:
                result.growth = True
                result.organism_snomed = earlier.organism_snomed
                result.quantitation = earlier.quantitation
                result.susceptibilities = [
                    SusceptibilityResult(antibiotic_loinc=x.antibiotic_loinc, interpretation=x.interpretation)
                    for x in earlier.susceptibilities
                ]
            results.append(result)
            continue
        first_of[spec_key] = result
        if culture is not None and rng.random() < float(culture.get("growth_prob", 0.0)) and org_ids:
            result.growth = True
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
