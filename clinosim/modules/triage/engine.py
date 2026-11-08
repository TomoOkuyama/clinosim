"""Triage module engine(Tier 1 #3 α-min-2 PR1).

Loader + 6-layer validator + JTAS/ESI level + arrival_mode sampling.
POST_ENCOUNTER enricher entry:triage_enricher(Task 3)。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from clinosim import determinism
from clinosim.datafiles import load_validated_yaml
from clinosim.modules._shared import is_jp, normalize_probabilities

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"

SUPPORTED_LEVEL_SYSTEMS: frozenset[str] = frozenset({"JTAS", "ESI"})
SUPPORTED_ARRIVAL_MODES: frozenset[str] = frozenset({"walk-in", "ambulance", "police", "helicopter", "private_vehicle"})
SUPPORTED_SEVERITIES: frozenset[str] = frozenset({"mild", "moderate", "severe"})


class _TriageSystem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    levels: dict[str, Any] = {}


class _ResourceRule(BaseModel):
    """ESI v4 resource rule (decision point C): the level for 0 / 1 / >= 2
    resource types, and which medication routes and procedure orders count."""

    model_config = ConfigDict(extra="forbid")

    level_by_count: list[str]
    parenteral_routes: list[str]
    non_resource_procedures: list[str]

    @field_validator("level_by_count")
    @classmethod
    def _three_levels(cls, levels: list[str]) -> list[str]:
        if len(levels) != 3 or any(lv not in {"3", "4", "5"} for lv in levels):
            raise ValueError(f"resource_rule.level_by_count must be 3 levels in 3-5, got {levels}")
        return levels


class TriageProtocols(BaseModel):
    """Shape of triage_protocols.yaml: both level systems with levels 1-5,
    the supported arrival modes, and a severity → level distribution that
    sums to ~1.0 for each severity."""

    model_config = ConfigDict(extra="forbid")

    triage_systems: dict[str, _TriageSystem]
    arrival_modes: list[str]
    severity_to_triage_distribution: dict[str, dict[str, float]]
    arrival_mode_base_distribution: dict[str, float]
    resource_rule: _ResourceRule
    arrival_mode_severity_multipliers: dict[str, dict[str, float]]

    @model_validator(mode="before")
    @classmethod
    def _not_empty(cls, data: Any) -> Any:
        if not data:
            raise ValueError("triage_protocols.yaml: empty top-level")
        if not isinstance(data.get("triage_systems"), dict):
            raise ValueError("triage_protocols.yaml: missing 'triage_systems' key")
        return data

    @field_validator("triage_systems")
    @classmethod
    def _both_systems_with_five_levels(cls, ts: dict[str, _TriageSystem]) -> dict[str, _TriageSystem]:
        if set(ts) != SUPPORTED_LEVEL_SYSTEMS:
            missing, extra = SUPPORTED_LEVEL_SYSTEMS - set(ts), set(ts) - SUPPORTED_LEVEL_SYSTEMS
            raise ValueError(
                f"triage_protocols.yaml triage_systems ↔ SUPPORTED_LEVEL_SYSTEMS "
                f"drift: missing={sorted(missing)}, extra={sorted(extra)} "
                f"(must be exactly JTAS+ESI)"
            )
        for sys_name, system in ts.items():
            if set(system.levels) != {"1", "2", "3", "4", "5"}:
                raise ValueError(
                    f"triage_protocols.yaml[{sys_name}]: levels must be exactly 1-5, got {sorted(system.levels)}"
                )
        return ts

    @field_validator("arrival_modes")
    @classmethod
    def _supported_arrival_modes(cls, modes: list[str]) -> list[str]:
        if set(modes) != SUPPORTED_ARRIVAL_MODES:
            raise ValueError("triage_protocols.yaml arrival_modes ↔ SUPPORTED_ARRIVAL_MODES drift")
        return modes

    @field_validator("severity_to_triage_distribution")
    @classmethod
    def _every_severity_sums_to_one(cls, dist: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        if set(dist) != SUPPORTED_SEVERITIES:
            raise ValueError("triage_protocols.yaml severity_to_triage_distribution keys drift")
        for sev, probs in dist.items():
            total = sum(probs.values())
            if not (0.99 <= total <= 1.01):
                raise ValueError(f"triage_protocols.yaml[severity={sev}] probs must sum to ~1.0, got {total}")
        return dist

    @field_validator("arrival_mode_base_distribution")
    @classmethod
    def _base_distribution_covers_the_arrival_modes(cls, base: dict[str, float]) -> dict[str, float]:
        if set(base) != SUPPORTED_ARRIVAL_MODES:
            raise ValueError("arrival_mode_base_distribution keys drift")
        return base


@lru_cache(maxsize=1)
def load_triage_protocols() -> dict[str, Any]:
    """Load triage_protocols.yaml + validate."""
    return load_validated_yaml(_REF_DIR / "triage_protocols.yaml", TriageProtocols)


def pick_triage_level(
    severity: str, level_system: str, rng: np.random.Generator, bounds: tuple[int, int] = (1, 5)
) -> str:
    """Sample triage level given severity + system (JTAS or ESI use same
    distribution), restricted to the ``bounds`` (most, least urgent) level
    (Issue #2864). When the severity puts no weight inside the bounds, the
    unrestricted draw is clamped into them. Either way one ``choice`` draw."""
    if level_system not in SUPPORTED_LEVEL_SYSTEMS:
        raise ValueError(f"unsupported level_system: {level_system}")
    protocols = load_triage_protocols()
    dist = protocols["severity_to_triage_distribution"][severity]
    lo, hi = bounds
    inside = [k for k in dist if lo <= int(k) <= hi and dist[k] > 0]
    if not inside:
        levels = list(dist.keys())
        probs = normalize_probabilities([dist[k] for k in levels], fallback="raise")
        return str(min(max(int(rng.choice(levels, p=probs)), lo), hi))
    probs = normalize_probabilities([dist[k] for k in inside], fallback="raise")
    return str(rng.choice(inside, p=probs))


def resource_count(orders: list[Any]) -> int:
    """Number of distinct ESI v4 resource types among the ED orders (Issue
    #2864): labs, imaging, parenteral treatment (IV fluids and IV / IM /
    nebulized medications) and procedures each count once; PO / topical
    medications, therapy orders and the simple procedures listed in
    ``resource_rule.non_resource_procedures`` are not resources."""
    rule = load_triage_protocols()["resource_rule"]
    parenteral = {r.casefold() for r in rule["parenteral_routes"]}
    simple = [k.casefold() for k in rule["non_resource_procedures"]]
    kinds: set[str] = set()
    for order in orders:
        order_type = str(_o(order, "order_type", "") or "")
        if order_type in ("lab", "imaging"):
            kinds.add(order_type)
        elif order_type == "medication" and str(_o(order, "route", "") or "").strip().casefold() in parenteral:
            kinds.add("parenteral")
        elif order_type == "procedure":
            name = str(_o(order, "display_name", "") or "").casefold()
            if not any(k in name for k in simple):
                kinds.add("procedure")
    return len(kinds)


def resource_level(orders: list[Any]) -> int:
    """ESI v4 level 3 / 4 / 5 for >= 2 / 1 / 0 resource types (Issue #2864)."""
    by_count = load_triage_protocols()["resource_rule"]["level_by_count"]
    return int(by_count[min(resource_count(orders), len(by_count) - 1)])


# Issue #2082: physiological floor on top of the severity-based draw (ESI /
# JTAS share the 1-5 numbering). Thresholds follow ESI v4 danger-zone vitals.
TRIAGE_DANGER_ZONE_HR: int = 100
TRIAGE_DANGER_ZONE_RR: int = 20
TRIAGE_DANGER_ZONE_SPO2: float = 92.0
TRIAGE_CRITICAL_SPO2: float = 90.0
TRIAGE_CRITICAL_SBP: int = 90
TRIAGE_SEVERE_PAIN: int = 7


def triage_level_cap(vitals: Any) -> int:
    """Highest (least urgent) level compatible with the triage vitals: 1 for an
    unresponsive patient; 2 for AVPU P, SpO2 < 90 or SBP < 90; 3 for
    danger-zone HR / RR / SpO2 or pain >= 7; otherwise 5 (no cap)."""
    loc = str(_o(vitals, "consciousness_level", "") or "")
    hr = _o(vitals, "heart_rate", None)
    rr = _o(vitals, "respiratory_rate", None)
    spo2 = _o(vitals, "spo2", None)
    sbp = _o(vitals, "systolic_bp", None)
    pain = _o(vitals, "pain_score", None)
    if loc == "U":
        return 1
    if (
        loc == "P"
        or (spo2 is not None and spo2 < TRIAGE_CRITICAL_SPO2)
        or (sbp is not None and sbp < TRIAGE_CRITICAL_SBP)
    ):
        return 2
    if (
        (hr is not None and hr > TRIAGE_DANGER_ZONE_HR)
        or (rr is not None and rr > TRIAGE_DANGER_ZONE_RR)
        or (spo2 is not None and spo2 < TRIAGE_DANGER_ZONE_SPO2)
        or (pain is not None and pain > TRIAGE_SEVERE_PAIN - 1)
    ):
        return 3
    return 5


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
from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed  # noqa: E402
from clinosim.types.triage import TriageData  # noqa: E402

ED_ENCOUNTER_TYPES: frozenset[str] = frozenset({"emergency"})


def _condition_spec(record: Any) -> dict[str, Any]:
    from clinosim.modules.encounter.protocol import load_all_encounter_conditions

    event = _o(record, "condition_event", None)
    names = _o(event, "ground_truth_diseases", None) or []
    return (load_all_encounter_conditions().get(str(names[0])) if names else None) or {}


def _triage_template(spec: dict[str, Any]) -> dict[str, Any]:
    return (spec.get("narrative") or {}).get("ed_triage_template") or {}


def condition_triage_bounds(record: Any) -> tuple[int, int]:
    """(most, least) urgent level the ED condition allows: the range of the
    encounter YAML's ``narrative.ed_triage_template.common_triage_levels``
    (Issue #2864), narrowed by ``triage_level_min`` / ``triage_level_max``
    (Issue #2124: suicidal ideation is an ESI v4 high-risk situation, level 2
    but not 1 without unstable vitals); (1, 5) when unset or the condition is
    unknown."""
    spec = _condition_spec(record)
    common = [int(lv) for lv in _triage_template(spec).get("common_triage_levels") or []]
    lo, hi = (min(common), max(common)) if common else (1, 5)
    lo = max(lo, int(spec.get("triage_level_min") or 1))
    hi = min(hi, int(spec.get("triage_level_max") or 5))
    return (lo, hi) if lo <= hi else (hi, hi)


def has_high_risk_order(record: Any, orders: list[Any]) -> bool:
    """True when the visit orders a treatment the condition lists under
    ``ed_triage_template.high_risk_orders`` (Issue #2864): an ESI v4 high-risk
    presentation such as anaphylaxis treated with IM epinephrine."""
    high_risk = set(_triage_template(_condition_spec(record)).get("high_risk_orders") or [])
    return any(str(_o(o, "display_name", "") or "") in high_risk for o in orders)


def triage_level(record: Any, enc: Any, drawn: int) -> int:
    """Triage level of an ED encounter from the bounded severity draw (Issue
    #2864): a drawn 1-2 stands; a drawn 3-5 becomes the ESI v4 resource level;
    a high-risk order makes it 2 at most; the result stays inside the
    condition bounds. The vitals cap (Issue #2082) applies last and may go
    below the bounds."""
    enc_id = _o(enc, "encounter_id", "")
    orders = [o for o in (_o(record, "orders", []) or []) if _o(o, "encounter_id", "") in ("", enc_id)]
    level = drawn if drawn <= 2 else resource_level(orders)
    if has_high_risk_order(record, orders):
        level = min(level, 2)
    lo, hi = condition_triage_bounds(record)
    level = min(max(level, lo), hi)
    enc_vitals = [v for v in (_o(record, "vital_signs", []) or []) if _o(v, "timestamp", None) is not None]
    if enc_vitals:
        arrival = min(enc_vitals, key=lambda v: _o(v, "timestamp", None))
        level = min(level, triage_level_cap(arrival))
    return level


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
            sub_seed = derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["triage"], enc_id)
            rng = determinism.default_rng(sub_seed)
            drawn = pick_triage_level(severity, level_system, rng, condition_triage_bounds(record))
            level = str(triage_level(record, enc, int(drawn)))
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
