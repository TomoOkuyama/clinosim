"""YAML validator tests for triage_protocols.yaml."""

from __future__ import annotations

import pytest

from clinosim.modules.triage.engine import (
    _validate_triage_protocols,
    load_triage_protocols,
)


def test_yaml_loads():
    p = load_triage_protocols()
    assert p


def test_validator_raises_on_empty():
    with pytest.raises(ValueError, match="empty"):
        _validate_triage_protocols({})


def test_validator_raises_on_missing_level_system():
    bad = {"triage_systems": {}, "arrival_modes": []}
    with pytest.raises(ValueError, match="JTAS.*ESI"):
        _validate_triage_protocols(bad)


def test_cached_lru():
    """@lru_cache(maxsize=1) — 2 calls same object."""
    assert load_triage_protocols() is load_triage_protocols()
