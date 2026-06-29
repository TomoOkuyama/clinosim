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
import yaml

from clinosim.modules._shared import normalize_probabilities
from clinosim.types.device import DeviceRecord

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


def _load_yaml(name: str) -> dict[str, Any]:
    with (_REF_DIR / name).open() as f:
        return yaml.safe_load(f)


def _validate_hai_organisms(data: dict) -> None:
    """Validate hai_organisms.yaml at load time — fail loud on cross-ref violations.

    Cross-references (silent-no-op risks) covered:
    1. top-level key 'hai_organisms' must exist and be a dict
    2. each hai_type ⊆ HAI_TYPES canonical set
    3. each organism list non-empty
    4. each weight numeric and >= 0
    5. each weight sum > 0 (zero-sum is the precondition that
       normalize_probabilities(fallback="raise") raises at runtime)
    6. each organism's snomed non-empty string

    HAI_TYPES is imported lazily inside the function to avoid the
    engine ↔ hai/__init__ circular import (engine is imported BY
    hai/__init__ during package init, so a top-level import here would
    fail at module load).
    """
    from clinosim.modules.hai import HAI_TYPES

    if not isinstance(data, dict):
        raise ValueError(
            f"hai_organisms.yaml: top-level must be a dict, "
            f"got {type(data).__name__}"
        )
    organisms_map = data.get("hai_organisms")
    if not isinstance(organisms_map, dict):
        raise ValueError(
            "hai_organisms.yaml: 'hai_organisms' must be a dict of "
            f"{{hai_type: [organisms]}}, got {type(organisms_map).__name__}"
        )
    valid_types = set(HAI_TYPES)
    for hai_type, organism_list in organisms_map.items():
        if hai_type not in valid_types:
            raise ValueError(
                f"hai_organisms.yaml: unknown HAI type {hai_type!r}; "
                f"expected one of {sorted(valid_types)}"
            )
        if not isinstance(organism_list, list) or not organism_list:
            raise ValueError(
                f"hai_organisms.yaml: hai_type {hai_type!r} has empty "
                f"organism list"
            )
        weights: list[float] = []
        for entry in organism_list:
            if not isinstance(entry, dict):
                raise ValueError(
                    f"hai_organisms.yaml: {hai_type!r} entry must be a "
                    f"dict, got {entry!r}"
                )
            snomed = entry.get("snomed")
            if not isinstance(snomed, str) or not snomed:
                raise ValueError(
                    f"hai_organisms.yaml: {hai_type!r} entry has empty "
                    f"SNOMED {snomed!r}"
                )
            try:
                w = float(entry.get("weight", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"hai_organisms.yaml: {hai_type!r}/{snomed!r} weight "
                    f"non-numeric: {entry.get('weight')!r}"
                ) from exc
            if w < 0:
                raise ValueError(
                    f"hai_organisms.yaml: {hai_type!r}/{snomed!r} has "
                    f"negative weight {w}"
                )
            weights.append(w)
        if sum(weights) <= 0:
            raise ValueError(
                f"hai_organisms.yaml: {hai_type!r} has zero-sum "
                f"weights {weights}"
            )

    # Forward-coverage (sibling sweep, 2026-06-29): every HAI_TYPE must have an entry.
    missing = valid_types - set(organisms_map.keys())
    if missing:
        raise ValueError(
            f"hai_organisms.yaml missing HAI_TYPES: {sorted(missing)!r}"
        )


def _validate_hai_rates(data: dict) -> None:
    """Validate hai_rates.yaml at load time (sibling sweep, 2026-06-29).

    6-layer silent-no-op defense:
    1. top-level 'hai_rates' must exist and be non-empty
    2. each hai_type ⊆ HAI_TYPES canonical set (no unknown keys)
    3. per-bucket non-empty
    4. HAI_TYPES forward-coverage (every canonical hai_type present)
    5. per_day_risk numeric and ∈ [0, 1]
    6. source_device_type ∈ load_devices_config()["devices"] (authoritative)
    """
    from clinosim.modules.device.engine import load_devices_config
    from clinosim.modules.hai import HAI_TYPES

    if not isinstance(data, dict):
        raise ValueError(
            f"hai_rates.yaml: top-level must be a dict, "
            f"got {type(data).__name__}"
        )
    rates = data.get("hai_rates") or {}
    if not rates:
        raise ValueError(
            "hai_rates.yaml top-level empty — silent no-op risk"
        )
    valid_types = set(HAI_TYPES)
    device_table = load_devices_config().get("devices", {})
    for hai_type, bucket in rates.items():
        if hai_type not in valid_types:
            raise ValueError(
                f"hai_rates.yaml: unknown hai_type {hai_type!r}, "
                f"expected one of {sorted(valid_types)}"
            )
        if not isinstance(bucket, dict) or not bucket:
            raise ValueError(
                f"hai_rates.yaml: {hai_type!r} bucket empty"
            )
        risk = bucket.get("per_day_risk")
        if not isinstance(risk, (int, float)) or not (0.0 <= float(risk) <= 1.0):
            raise ValueError(
                f"hai_rates.yaml: {hai_type!r} per_day_risk {risk!r} "
                f"not in [0, 1]"
            )
        src = bucket.get("source_device_type", "")
        if src not in device_table:
            raise ValueError(
                f"hai_rates.yaml: {hai_type!r} source_device_type {src!r} "
                f"not in devices.yaml ({sorted(device_table.keys())})"
            )
    missing = valid_types - set(rates.keys())
    if missing:
        raise ValueError(
            f"hai_rates.yaml missing HAI_TYPES: {sorted(missing)!r}"
        )


@lru_cache(maxsize=1)
def load_hai_rates() -> dict[str, Any]:
    data = _load_yaml("hai_rates.yaml")
    _validate_hai_rates(data)
    return data


def _code_in_data(system: str, code: str) -> bool:
    """Direct membership check in codes/data/<system>.yaml.

    Used by sibling sweep validators (`_validate_hai_codes`,
    `_validate_hai_specimens`) — `lookup()` returns the code itself as
    fallback for unknown entries (not None), so it can't distinguish
    "code exists" from "code absent". Direct `cs.codes` membership IS
    the authoritative check.

    pr121-adv-1 fix (Agent 1 Minor #2): raise ValueError when the
    system itself is unregistered, rather than collapsing into "code
    missing". Prevents a future codes/ rename / deletion from
    masquerading as per-code errors across every hai YAML validator.
    """
    from clinosim.codes.loader import _load_system

    cs = _load_system(system)
    if cs is None:
        raise ValueError(
            f"_code_in_data: code system {system!r} not registered in "
            f"clinosim/codes/data/ — system itself is missing, not the code"
        )
    return code in cs.codes


def _validate_hai_codes(data: dict) -> None:
    """Validate hai_codes.yaml at load time (sibling sweep).

    Cross-validation via authoritative loaders:
    - icd10_us_billable ∈ codes/data/icd-10-cm.yaml
    - icd10_jp_who     ∈ codes/data/icd-10.yaml
    - snomed           ∈ codes/data/snomed-ct.yaml
    """
    from clinosim.modules.hai import HAI_TYPES

    if not isinstance(data, dict):
        raise ValueError(
            f"hai_codes.yaml: top-level must be a dict, "
            f"got {type(data).__name__}"
        )
    codes_table = data.get("hai_codes") or {}
    if not codes_table:
        raise ValueError("hai_codes.yaml top-level empty — silent no-op risk")
    valid_types = set(HAI_TYPES)
    for hai_type, bucket in codes_table.items():
        if hai_type not in valid_types:
            raise ValueError(
                f"hai_codes.yaml: unknown hai_type {hai_type!r}, "
                f"expected one of {sorted(valid_types)}"
            )
        if not isinstance(bucket, dict) or not bucket:
            raise ValueError(f"hai_codes.yaml: {hai_type!r} bucket empty")
        icd_us = bucket.get("icd10_us_billable", "")
        if not _code_in_data("icd-10-cm", icd_us):
            raise ValueError(
                f"hai_codes.yaml: {hai_type!r} icd10_us_billable {icd_us!r} "
                f"not in codes/data/icd-10-cm.yaml"
            )
        icd_jp = bucket.get("icd10_jp_who", "")
        if not _code_in_data("icd-10", icd_jp):
            raise ValueError(
                f"hai_codes.yaml: {hai_type!r} icd10_jp_who {icd_jp!r} "
                f"not in codes/data/icd-10.yaml"
            )
        snomed = bucket.get("snomed", "")
        if not _code_in_data("snomed-ct", snomed):
            raise ValueError(
                f"hai_codes.yaml: {hai_type!r} snomed {snomed!r} "
                f"not in codes/data/snomed-ct.yaml"
            )
    missing = valid_types - set(codes_table.keys())
    if missing:
        raise ValueError(
            f"hai_codes.yaml missing HAI_TYPES: {sorted(missing)!r}"
        )


@lru_cache(maxsize=1)
def load_hai_codes() -> dict[str, Any]:
    data = _load_yaml("hai_codes.yaml")
    _validate_hai_codes(data)
    return data


@lru_cache(maxsize=1)
def load_hai_organisms() -> dict[str, Any]:
    data = _load_yaml("hai_organisms.yaml")
    _validate_hai_organisms(data)
    return data


def _validate_hai_specimens(data: dict) -> None:
    """Validate hai_specimens.yaml at load time (sibling sweep).

    Cross-validation via authoritative loaders:
    - specimen_snomed ∈ codes/data/snomed-ct.yaml
    - test_loinc      ∈ codes/data/loinc.yaml
    """
    from clinosim.modules.hai import HAI_TYPES

    if not isinstance(data, dict):
        raise ValueError(
            f"hai_specimens.yaml: top-level must be a dict, "
            f"got {type(data).__name__}"
        )
    spec_table = data.get("hai_specimens") or {}
    if not spec_table:
        raise ValueError("hai_specimens.yaml top-level empty — silent no-op risk")
    valid_types = set(HAI_TYPES)
    for hai_type, bucket in spec_table.items():
        if hai_type not in valid_types:
            raise ValueError(
                f"hai_specimens.yaml: unknown hai_type {hai_type!r}, "
                f"expected one of {sorted(valid_types)}"
            )
        if not isinstance(bucket, dict) or not bucket:
            raise ValueError(f"hai_specimens.yaml: {hai_type!r} bucket empty")
        snomed = bucket.get("specimen_snomed", "")
        if not _code_in_data("snomed-ct", snomed):
            raise ValueError(
                f"hai_specimens.yaml: {hai_type!r} specimen_snomed {snomed!r} "
                f"not in codes/data/snomed-ct.yaml"
            )
        loinc = bucket.get("test_loinc", "")
        if not _code_in_data("loinc", loinc):
            raise ValueError(
                f"hai_specimens.yaml: {hai_type!r} test_loinc {loinc!r} "
                f"not in codes/data/loinc.yaml"
            )
    missing = valid_types - set(spec_table.keys())
    if missing:
        raise ValueError(
            f"hai_specimens.yaml missing HAI_TYPES: {sorted(missing)!r}"
        )


@lru_cache(maxsize=1)
def load_hai_specimens() -> dict[str, Any]:
    data = _load_yaml("hai_specimens.yaml")
    _validate_hai_specimens(data)
    return data


def sample_hai_onset(
    device: DeviceRecord,
    rate_cfg: dict,
    rng: np.random.Generator,
) -> tuple[bool, int | None]:
    """Return (occurred, onset_day_offset) for this device.

    Returns (False, None) when (a) line_days<2 (CDC >=48h rule) or
    (b) rng draw exceeds cumulative probability over the device's
    line-days.

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
