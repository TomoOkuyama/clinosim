"""Healthcare system configuration loader."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

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
    country_map = {"JP": "japan.yaml", "US": "us.yaml"}
    filename = country_map.get(country)
    if filename is None:
        raise ValueError(f"Unsupported country: {country}. Supported: {list(country_map.keys())}")

    config_path = _CONFIG_DIR / filename
    if not config_path.exists():
        raise FileNotFoundError(f"Healthcare config not found: {config_path}")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    return HealthcareSystemConfig(**data)
