"""Triage module engine(Tier 1 #3 α-min-2 PR1).

Loader + 6-layer validator + JTAS/ESI level + arrival_mode sampling.
POST_ENCOUNTER enricher entry:triage_enricher(Task 3)。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from clinosim.modules._shared import normalize_probabilities

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"

SUPPORTED_LEVEL_SYSTEMS: frozenset[str] = frozenset({"JTAS", "ESI"})
SUPPORTED_ARRIVAL_MODES: frozenset[str] = frozenset(
    {"walk-in", "ambulance", "police", "helicopter", "private_vehicle"}
)
SUPPORTED_SEVERITIES: frozenset[str] = frozenset({"mild", "moderate", "severe"})


def _validate_triage_protocols(data: dict[str, Any]) -> None:
    """6-layer silent-no-op defense for triage_protocols.yaml."""
    if not data:
        raise ValueError("triage_protocols.yaml: empty top-level")
    ts = data.get("triage_systems")
    if ts is None or not isinstance(ts, dict):
        raise ValueError("triage_protocols.yaml: missing 'triage_systems' key")
    yaml_systems = set(ts.keys())
    if yaml_systems != SUPPORTED_LEVEL_SYSTEMS:
        missing = SUPPORTED_LEVEL_SYSTEMS - yaml_systems
        extra = yaml_systems - SUPPORTED_LEVEL_SYSTEMS
        raise ValueError(
            f"triage_protocols.yaml triage_systems ↔ SUPPORTED_LEVEL_SYSTEMS "
            f"drift: missing={sorted(missing)}, extra={sorted(extra)} "
            f"(must be exactly JTAS+ESI)"
        )
    # per-system level 1..5 all present
    for sys_name, sys_data in ts.items():
        levels = sys_data.get("levels", {})
        if set(levels.keys()) != {"1", "2", "3", "4", "5"}:
            raise ValueError(
                f"triage_protocols.yaml[{sys_name}]: levels must be exactly 1-5, "
                f"got {sorted(levels.keys())}"
            )
    # arrival_modes cross-validated
    arr = data.get("arrival_modes", [])
    if set(arr) != SUPPORTED_ARRIVAL_MODES:
        raise ValueError(
            f"triage_protocols.yaml arrival_modes ↔ SUPPORTED_ARRIVAL_MODES drift"
        )
    # severity_to_triage_distribution: all 3 severities present, each sums to ~1.0
    dist = data.get("severity_to_triage_distribution", {})
    if set(dist.keys()) != SUPPORTED_SEVERITIES:
        raise ValueError(
            f"triage_protocols.yaml severity_to_triage_distribution keys drift"
        )
    for sev, probs in dist.items():
        total = sum(probs.values())
        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"triage_protocols.yaml[severity={sev}] probs must sum to ~1.0, got {total}"
            )
    # arrival_mode_base_distribution: keys must match SUPPORTED_ARRIVAL_MODES
    base = data.get("arrival_mode_base_distribution", {})
    if set(base.keys()) != SUPPORTED_ARRIVAL_MODES:
        raise ValueError("arrival_mode_base_distribution keys drift")


@lru_cache(maxsize=1)
def load_triage_protocols() -> dict[str, Any]:
    """Load triage_protocols.yaml + validate."""
    with (_REF_DIR / "triage_protocols.yaml").open() as f:
        data = yaml.safe_load(f)
    _validate_triage_protocols(data)
    return data


def pick_triage_level(severity: str, level_system: str, rng: np.random.Generator) -> str:
    """Sample triage level given severity + system (JTAS or ESI use same distribution)."""
    if level_system not in SUPPORTED_LEVEL_SYSTEMS:
        raise ValueError(f"unsupported level_system: {level_system}")
    protocols = load_triage_protocols()
    dist = protocols["severity_to_triage_distribution"][severity]
    levels = list(dist.keys())
    probs = normalize_probabilities([dist[k] for k in levels], fallback="raise")
    return str(rng.choice(levels, p=probs))


def pick_arrival_mode(severity: str, rng: np.random.Generator) -> str:
    """Sample arrival mode given severity."""
    protocols = load_triage_protocols()
    base = protocols["arrival_mode_base_distribution"]
    mults = protocols["arrival_mode_severity_multipliers"][severity]
    weights = {m: base[m] * mults.get(m, 1.0) for m in base}
    modes = list(weights.keys())
    probs = normalize_probabilities([weights[m] for m in modes], fallback="raise")
    return str(rng.choice(modes, p=probs))
