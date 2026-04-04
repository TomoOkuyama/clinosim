"""Healthcare system configuration loader."""

from __future__ import annotations

from pathlib import Path

import yaml

from clinosim.types.config import HealthcareSystemConfig

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def load_healthcare_config(country: str) -> HealthcareSystemConfig:
    """Load country-specific healthcare configuration from YAML."""
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
