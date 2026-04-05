"""Encounter condition protocol loader — YAML-driven ED/outpatient conditions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REFERENCE_DATA_DIR = Path(__file__).parent / "reference_data"

_cache: dict[str, dict[str, Any]] | None = None


def load_encounter_condition(condition_id: str) -> dict[str, Any]:
    """Load a single encounter condition YAML."""
    path = _REFERENCE_DATA_DIR / f"{condition_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Encounter condition not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def load_all_encounter_conditions() -> dict[str, dict[str, Any]]:
    """Auto-discover and load all encounter condition YAMLs. Cached."""
    global _cache
    if _cache is not None:
        return _cache
    conditions: dict[str, dict[str, Any]] = {}
    for yaml_file in sorted(_REFERENCE_DATA_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_file.read_text())
            cid = data.get("condition_id", yaml_file.stem)
            conditions[cid] = data
        except Exception:
            pass
    _cache = conditions
    return conditions
