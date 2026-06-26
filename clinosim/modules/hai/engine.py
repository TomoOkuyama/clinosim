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


@lru_cache(maxsize=1)
def load_hai_rates() -> dict[str, Any]:
    return _load_yaml("hai_rates.yaml")


@lru_cache(maxsize=1)
def load_hai_codes() -> dict[str, Any]:
    return _load_yaml("hai_codes.yaml")


@lru_cache(maxsize=1)
def load_hai_organisms() -> dict[str, Any]:
    return _load_yaml("hai_organisms.yaml")


@lru_cache(maxsize=1)
def load_hai_specimens() -> dict[str, Any]:
    return _load_yaml("hai_specimens.yaml")


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
    p = normalize_probabilities([w["weight"] for w in weights])
    return str(rng.choice(snomeds, p=p))


def _add_days(iso_date: str, n: int) -> str:
    """Return iso_date + n days as ISO YYYY-MM-DD string."""
    return (date.fromisoformat(iso_date) + timedelta(days=n)).isoformat()
