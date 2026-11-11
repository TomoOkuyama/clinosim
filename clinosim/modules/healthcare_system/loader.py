"""Healthcare system configuration loader."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from clinosim.country_profile import country_profile
from clinosim.types.config import HealthcareSystemConfig

_HERE = Path(__file__).resolve().parent
_CONFIG_DIR = _HERE.parents[1] / "config"


@lru_cache(maxsize=2)
def load_healthcare_config(country: str) -> HealthcareSystemConfig:
    """Load country-specific healthcare configuration from YAML.

    Cached (maxsize=2 for US + JP): the returned ``HealthcareSystemConfig`` is a
    shared read-only instance — callers must not mutate it. Called in the hot
    simulation path (``simulator/engine.py``).
    """
    # Issue #3192: the file is named by the country profile
    # (``healthcare_system``); a country without a profile or without one
    # raises KeyError.
    profile = country_profile(country)
    if profile.healthcare_system is None:
        raise KeyError(f"country {profile.code} names no healthcare_system in its country profile")

    config_path = _CONFIG_DIR / f"{profile.healthcare_system}.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Healthcare config not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return HealthcareSystemConfig(**data)
