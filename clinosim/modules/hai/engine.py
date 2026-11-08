"""Pure functions for the hai module (AD-55 PR-B).

sample_hai_onset takes a DeviceRecord + CDC NHSN rate config + sub-rng
and returns (occurred, onset_offset). _sample_organism is a weighted
choice over the organism distribution. Loaders are @lru_cache'd YAML
readers. State unchanged (BNP-pattern surgical principle).
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from clinosim.codes import code_exists
from clinosim.datafiles import load_validated_yaml
from clinosim.modules._shared import normalize_probabilities
from clinosim.types.device import DeviceRecord

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


def _hai_types() -> set[str]:
    # Imported lazily: engine is imported BY hai/__init__ during package init,
    # so a top-level import of HAI_TYPES would be circular.
    from clinosim.modules.hai import HAI_TYPES

    return set(HAI_TYPES)


def _top_level_dict(data: Any, file: str) -> Any:
    if not isinstance(data, dict):
        raise ValueError(f"{file}: top-level must be a dict, got {type(data).__name__}")
    return data


def _non_empty_table(data: Any, file: str, section: str) -> Any:
    if not _top_level_dict(data, file).get(section):
        raise ValueError(f"{file} top-level empty — silent-no-op risk")
    return data


def _known_hai_types(keys: set[str], file: str, unknown_label: str = "hai_type") -> None:
    valid = _hai_types()
    for hai_type in sorted(keys - valid):
        raise ValueError(f"{file}: unknown {unknown_label} {hai_type!r}, expected one of {sorted(valid)}")


def _every_hai_type(keys: set[str], file: str) -> None:
    """Forward coverage (sibling sweep, 2026-06-29): every HAI_TYPE has an entry."""
    missing = _hai_types() - keys
    if missing:
        raise ValueError(f"{file} missing HAI_TYPES: {sorted(missing)!r}")


def _non_empty_bucket(bucket: Any, file: str) -> Any:
    if not isinstance(bucket, dict) or not bucket:
        raise ValueError(f"{file}: bucket empty")
    return bucket


def _registered(system: str, code: str, file: str, field: str, authority: str) -> str:
    if not code_exists(system, code, exact=True):
        raise ValueError(f"{file}: {field} {code!r} not in codes/data/{authority}")
    return code


class _HaiOrganism(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snomed: str
    weight: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def _is_a_mapping(cls, entry: Any) -> Any:
        if not isinstance(entry, dict):
            raise ValueError(f"hai_organisms.yaml: entry must be a dict, got {entry!r}")
        return entry

    @field_validator("snomed", mode="before")
    @classmethod
    def _non_empty_snomed(cls, snomed: Any) -> Any:
        if not isinstance(snomed, str) or not snomed:
            raise ValueError(f"hai_organisms.yaml: entry has empty SNOMED {snomed!r}")
        return snomed

    @field_validator("weight", mode="before")
    @classmethod
    def _non_negative_number(cls, weight: Any) -> float:
        try:
            w = float(weight)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"hai_organisms.yaml: weight non-numeric: {weight!r}") from exc
        if w < 0:
            raise ValueError(f"hai_organisms.yaml: entry has negative weight {w}")
        return w


class HaiOrganisms(BaseModel):
    """Shape of hai_organisms.yaml: a non-empty organism list with registered
    SNOMED codes and non-negative weights of positive sum (the precondition of
    ``normalize_probabilities(fallback="raise")``) for exactly the HAI_TYPES."""

    model_config = ConfigDict(extra="forbid")

    hai_organisms: dict[str, list[_HaiOrganism]]

    @model_validator(mode="before")
    @classmethod
    def _is_a_mapping(cls, data: Any) -> Any:
        return _top_level_dict(data, "hai_organisms.yaml")

    @field_validator("hai_organisms", mode="before")
    @classmethod
    def _known_types_with_organisms(cls, organisms: Any) -> Any:
        if not isinstance(organisms, dict):
            raise ValueError(
                "hai_organisms.yaml: 'hai_organisms' must be a dict of "
                f"{{hai_type: [organisms]}}, got {type(organisms).__name__}"
            )
        _known_hai_types(set(organisms), "hai_organisms.yaml", "HAI type")
        for hai_type, organism_list in organisms.items():
            if not isinstance(organism_list, list) or not organism_list:
                raise ValueError(f"hai_organisms.yaml: hai_type {hai_type!r} has empty organism list")
        return organisms

    @field_validator("hai_organisms")
    @classmethod
    def _positive_weights_for_every_type(
        cls, organisms: dict[str, list[_HaiOrganism]]
    ) -> dict[str, list[_HaiOrganism]]:
        for hai_type, organism_list in organisms.items():
            weights = [o.weight for o in organism_list]
            if sum(weights) <= 0:
                raise ValueError(f"hai_organisms.yaml: {hai_type!r} has zero-sum weights {weights}")
        _every_hai_type(set(organisms), "hai_organisms.yaml")
        return organisms


class _HaiRate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    per_day_risk: Any
    source_device_type: Any = ""

    @model_validator(mode="before")
    @classmethod
    def _non_empty(cls, bucket: Any) -> Any:
        return _non_empty_bucket(bucket, "hai_rates.yaml")

    @field_validator("per_day_risk")
    @classmethod
    def _probability(cls, risk: Any) -> Any:
        if not isinstance(risk, (int, float)) or not 0.0 <= float(risk) <= 1.0:
            raise ValueError(f"hai_rates.yaml: per_day_risk {risk!r} not in [0, 1]")
        return risk

    @model_validator(mode="after")
    def _known_device_with_risk(self) -> _HaiRate:
        from clinosim.modules.device.engine import load_devices_config

        devices = load_devices_config().get("devices", {})
        if self.source_device_type not in devices:
            raise ValueError(
                f"hai_rates.yaml: source_device_type {self.source_device_type!r} "
                f"not in devices.yaml ({sorted(devices)})"
            )
        return self


class HaiRates(BaseModel):
    """Shape of hai_rates.yaml: for exactly the HAI_TYPES, a per-day risk in
    [0, 1] and a source device type from devices.yaml (the authority)."""

    model_config = ConfigDict(extra="forbid")

    hai_rates: dict[str, _HaiRate]

    @model_validator(mode="before")
    @classmethod
    def _not_empty(cls, data: Any) -> Any:
        return _non_empty_table(data, "hai_rates.yaml", "hai_rates")

    @field_validator("hai_rates", mode="before")
    @classmethod
    def _known_types(cls, rates: Any) -> Any:
        _known_hai_types(set(rates), "hai_rates.yaml")
        return rates

    @field_validator("hai_rates")
    @classmethod
    def _every_type(cls, rates: dict[str, _HaiRate]) -> dict[str, _HaiRate]:
        _every_hai_type(set(rates), "hai_rates.yaml")
        return rates


class _HaiCode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    icd10_us_billable: Any = ""
    snomed: Any = ""

    @model_validator(mode="before")
    @classmethod
    def _non_empty(cls, bucket: Any) -> Any:
        return _non_empty_bucket(bucket, "hai_codes.yaml")

    @model_validator(mode="after")
    def _registered_codes(self) -> _HaiCode:
        from clinosim.locale.loader import load_code_mapping

        icd_us = self.icd10_us_billable
        _registered("icd-10-cm", icd_us, "hai_codes.yaml", "icd10_us_billable", "icd-10-cm.yaml")
        # The one CM → WHO crosswalk (Issue #2257); codes absent from it pass
        # through unchanged, as at emission.
        icd_jp = str(load_code_mapping("diagnosis", "JP").get(icd_us, icd_us))
        if not code_exists("icd-10", icd_jp, exact=True):
            raise ValueError(
                f"hai_codes.yaml: JP code {icd_jp!r} of {icd_us!r} "
                "(locale/jp/code_mapping_diagnosis.yaml) not in codes/data/icd-10.yaml"
            )
        _registered("snomed-ct", self.snomed, "hai_codes.yaml", "snomed", "snomed-ct.yaml")
        return self


class HaiCodes(BaseModel):
    """Shape of hai_codes.yaml: for exactly the HAI_TYPES, an ICD-10-CM code
    (whose JP crosswalk code is a WHO ICD-10 code) and a SNOMED code, all
    registered in clinosim/codes/data."""

    model_config = ConfigDict(extra="forbid")

    hai_codes: dict[str, _HaiCode]

    @model_validator(mode="before")
    @classmethod
    def _not_empty(cls, data: Any) -> Any:
        return _non_empty_table(data, "hai_codes.yaml", "hai_codes")

    @field_validator("hai_codes", mode="before")
    @classmethod
    def _known_types(cls, codes: Any) -> Any:
        _known_hai_types(set(codes), "hai_codes.yaml")
        return codes

    @field_validator("hai_codes")
    @classmethod
    def _every_type(cls, codes: dict[str, _HaiCode]) -> dict[str, _HaiCode]:
        _every_hai_type(set(codes), "hai_codes.yaml")
        return codes


class _HaiSpecimen(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Microbiology specimen key (microbiology.yaml ``specimens``) of the culture.
    specimen: str
    specimen_snomed: Any = ""
    test_loinc: Any = ""

    @model_validator(mode="before")
    @classmethod
    def _non_empty(cls, bucket: Any) -> Any:
        return _non_empty_bucket(bucket, "hai_specimens.yaml")

    @model_validator(mode="after")
    def _registered_codes(self) -> _HaiSpecimen:
        _registered("snomed-ct", self.specimen_snomed, "hai_specimens.yaml", "specimen_snomed", "snomed-ct.yaml")
        _registered("loinc", self.test_loinc, "hai_specimens.yaml", "test_loinc", "loinc.yaml")
        return self


class HaiSpecimens(BaseModel):
    """Shape of hai_specimens.yaml: for exactly the HAI_TYPES, a specimen
    SNOMED code and a culture LOINC code registered in clinosim/codes/data."""

    model_config = ConfigDict(extra="forbid")

    hai_specimens: dict[str, _HaiSpecimen]

    @model_validator(mode="before")
    @classmethod
    def _not_empty(cls, data: Any) -> Any:
        return _non_empty_table(data, "hai_specimens.yaml", "hai_specimens")

    @field_validator("hai_specimens", mode="before")
    @classmethod
    def _known_types(cls, specimens: Any) -> Any:
        _known_hai_types(set(specimens), "hai_specimens.yaml")
        return specimens

    @field_validator("hai_specimens")
    @classmethod
    def _every_type(cls, specimens: dict[str, _HaiSpecimen]) -> dict[str, _HaiSpecimen]:
        _every_hai_type(set(specimens), "hai_specimens.yaml")
        return specimens


@lru_cache(maxsize=1)
def load_hai_rates() -> dict[str, Any]:
    return load_validated_yaml(_REF_DIR / "hai_rates.yaml", HaiRates)


@lru_cache(maxsize=1)
def load_hai_codes() -> dict[str, Any]:
    return load_validated_yaml(_REF_DIR / "hai_codes.yaml", HaiCodes)


def hai_icd10_code(hai_type: str) -> str:
    """The ICD-10-CM code the HAI enricher emits for ``hai_type``, from
    ``hai_codes.yaml`` (Issue #2301: audits read it here, not restated)."""
    return str(load_hai_codes()["hai_codes"][hai_type]["icd10_us_billable"])


@lru_cache(maxsize=1)
def load_hai_organisms() -> dict[str, Any]:
    return load_validated_yaml(_REF_DIR / "hai_organisms.yaml", HaiOrganisms)


@lru_cache(maxsize=1)
def load_hai_specimens() -> dict[str, Any]:
    return load_validated_yaml(_REF_DIR / "hai_specimens.yaml", HaiSpecimens)


def sample_hai_onset(
    device: DeviceRecord,
    rate_cfg: dict,
    rng: np.random.Generator,
) -> tuple[bool, int | None]:
    """Return (occurred, onset_day_offset) for this device.

    Returns (False, None) when (a) line_days<2 (CDC >=48h rule),
    (b) rng draw exceeds cumulative probability over the device's
    line-days, or (c) line_days == 2 (no eligible onset day in [2, 2)).

    Returns (True, k) when onset occurs on placement_date + k days,
    k uniformly drawn from [2, line_days).

    Snapshot in-progress (device.removal_date is None) uses a
    conservative line_days = 7 (Phase 2 simplification).
    """
    placement = date.fromisoformat(device.placement_date)
    if device.removal_date:
        line_days = (date.fromisoformat(device.removal_date) - placement).days
    else:
        line_days = 7
    if line_days < 2:
        return (False, None)
    per_day_risk = rate_cfg["per_day_risk"]
    cumulative = 1 - (1 - per_day_risk) ** line_days
    if rng.random() >= cumulative:
        return (False, None)
    if line_days <= 2:
        # Onset is drawn from [2, line_days); a 2-day line has no eligible
        # day. The firing draw above is still consumed (RNG stream unchanged).
        return (False, None)
    onset_offset = int(rng.integers(2, line_days))
    return (True, onset_offset)


def _sample_organism(weights: list[dict], rng: np.random.Generator) -> str:
    """Weighted choice over [{snomed, weight}, ...] returning the snomed."""
    snomeds = [w["snomed"] for w in weights]
    p = normalize_probabilities([w["weight"] for w in weights], fallback="raise")
    return str(rng.choice(snomeds, p=p))


def _add_days(iso_date: str, n: int) -> str:
    """Return iso_date + n days as ISO YYYY-MM-DD string."""
    return (date.fromisoformat(iso_date) + timedelta(days=n)).isoformat()
