"""Unit tests for the `target_los_config` canonical resolver (Issue #550).

Locks:
- Direct hit returns the exact dict from the protocol
- Country fallback to `"us"` when the requested country_key is absent
- Returns `None` when the (country, severity) slot is missing so the caller
  can apply its own domain-appropriate default
- Unknown country codes normalize to `"us"` (default-US convention)
- Non-dict severity values (e.g. `None`) return `None`
"""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.disease.localization import target_los_config


def _mk_proto(target_los: dict) -> SimpleNamespace:
    """Test double — the resolver only reads ``.target_los``."""
    return SimpleNamespace(target_los=target_los)


def test_direct_hit_returns_exact_dict() -> None:
    proto = _mk_proto({"us": {"moderate": {"mean": 7.0, "sd": 2.0, "min": 3, "max": 14}}})
    cfg = target_los_config(proto, "US", "moderate")
    assert cfg == {"mean": 7.0, "sd": 2.0, "min": 3, "max": 14}


def test_jp_country_maps_to_japan_key() -> None:
    proto = _mk_proto({"japan": {"severe": {"mean": 21.0, "sd": 5.0, "min": 10, "max": 45}}})
    cfg = target_los_config(proto, "JP", "severe")
    assert cfg == {"mean": 21.0, "sd": 5.0, "min": 10, "max": 45}


def test_missing_country_falls_back_to_us() -> None:
    """Locks the country fallback ladder (inpatient's pre-canonical behaviour)."""
    proto = _mk_proto({"us": {"mild": {"mean": 3.0, "sd": 1.0, "min": 1, "max": 7}}})
    cfg = target_los_config(proto, "JP", "mild")
    assert cfg == {"mean": 3.0, "sd": 1.0, "min": 1, "max": 7}


def test_missing_severity_returns_none() -> None:
    """No severity fallback — caller decides how to interpret ``None``."""
    proto = _mk_proto({"us": {"moderate": {"mean": 7.0, "sd": 2.0, "min": 3, "max": 14}}})
    cfg = target_los_config(proto, "US", "critical")
    assert cfg is None


def test_missing_country_and_us_returns_none() -> None:
    """If neither the requested country nor ``us`` has an entry, no fallback exists."""
    proto = _mk_proto({"japan": {"moderate": {"mean": 14.0, "sd": 4.0, "min": 5, "max": 30}}})
    cfg = target_los_config(proto, "US", "moderate")
    # US requested → country_key="us" → not in dict → falls back to "us" (still absent) → None
    assert cfg is None


def test_unknown_country_normalizes_to_us() -> None:
    proto = _mk_proto({"us": {"moderate": {"mean": 7.0, "sd": 2.0, "min": 3, "max": 14}}})
    cfg = target_los_config(proto, "XX", "moderate")
    assert cfg == {"mean": 7.0, "sd": 2.0, "min": 3, "max": 14}


def test_empty_target_los_returns_none() -> None:
    proto = _mk_proto({})
    cfg = target_los_config(proto, "US", "moderate")
    assert cfg is None


def test_non_dict_severity_value_returns_none() -> None:
    """Defensive against malformed YAML — a severity value that is not a dict
    (e.g. accidentally left as a string or None) resolves to ``None`` rather
    than propagating a type error to the caller."""
    proto = _mk_proto({"us": {"moderate": None}})
    cfg = target_los_config(proto, "US", "moderate")
    assert cfg is None
