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

from clinosim.modules._shared import is_jp, normalize_probabilities

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


# ---------------------------------------------------------------------------
# POST_ENCOUNTER enricher (Task 3)
# ---------------------------------------------------------------------------

from datetime import datetime  # noqa: E402 — kept here to avoid circular import at module top

from clinosim.modules._shared import get_attr_or_key as _o  # noqa: E402
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed  # noqa: E402
from clinosim.types.triage import TriageData  # noqa: E402

ED_ENCOUNTER_TYPES: frozenset[str] = frozenset({"emergency"})


def triage_enricher(ctx: Any) -> None:
    """POST_ENCOUNTER enricher: populate triage_data on ED encounters.

    Country-gated: JP→JTAS、US→ESI。
    Determinism via derive_sub_seed(master, ENRICHER_SEED_OFFSETS["triage"],
    encounter_id)。Master stream 不変。

    Country resolution: primary source is ``ctx.config.country`` (production
    EnricherContext shape; matches document_enricher). Falls back to
    ``ctx.country`` for test-fixture SimpleNamespace ctx that sets country
    directly on the ctx object (backwards-compat with pre-2026-07-01 tests).
    """
    # Prefer ctx.config.country (production EnricherContext shape); fall back to
    # ctx.country (SimpleNamespace test fixtures). Without the ctx.config path
    # every production call defaulted to "us" → JP cohort silently produced ESI
    # instead of JTAS (PR-90 class silent-no-op; fixed 2026-07-01).
    config = _o(ctx, "config", None)
    country = (_o(config, "country", None) or _o(ctx, "country", "us") or "us").lower()
    level_system = "JTAS" if is_jp(country) else "ESI"
    records = _o(ctx, "records", []) or []
    for record in records:
        encounters = _o(record, "encounters", []) or []
        for enc in encounters:
            enc_type = _o(enc, "encounter_type", "")
            # enum vs str dual-access
            enc_type_str = enc_type.value if hasattr(enc_type, "value") else str(enc_type)
            if enc_type_str.lower() not in ED_ENCOUNTER_TYPES:
                continue
            severity = _o(enc, "severity", "moderate") or "moderate"
            enc_id = _o(enc, "encounter_id", "")
            sub_seed = derive_sub_seed(
                ctx.master_seed, ENRICHER_SEED_OFFSETS["triage"], enc_id
            )
            rng = np.random.default_rng(sub_seed)
            level = pick_triage_level(severity, level_system, rng)
            arrival_mode = pick_arrival_mode(severity, rng)
            admission_dt = _o(enc, "admission_datetime", None)
            triage_time = admission_dt if isinstance(admission_dt, datetime) else None
            enc.triage_data = TriageData(
                level=level,
                level_system=level_system,
                arrival_mode=arrival_mode,
                triage_time=triage_time,
                acuity_score=None,  # acuity_score は α-min-2 で未 populate、β-JP-1 で追加
                chief_complaint_summary=_o(enc, "chief_complaint", "") or "",
            )
