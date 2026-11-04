"""YAML validator tests for triage_protocols.yaml."""

from __future__ import annotations

import copy

import pytest

from clinosim.modules.triage.engine import TriageProtocols, load_triage_protocols


def test_yaml_loads():
    p = load_triage_protocols()
    assert p


def test_validator_raises_on_empty():
    with pytest.raises(ValueError, match="empty"):
        TriageProtocols.model_validate({})


def test_validator_raises_on_missing_level_system():
    bad = {"triage_systems": {}, "arrival_modes": []}
    with pytest.raises(ValueError, match="JTAS.*ESI"):
        TriageProtocols.model_validate(bad)


def _shipped() -> dict:
    return copy.deepcopy(load_triage_protocols())


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (lambda d: d["triage_systems"]["ESI"]["levels"].pop("5"), "levels must be exactly 1-5"),
        (lambda d: d["arrival_modes"].append("boat"), "arrival_modes"),
        (lambda d: d["severity_to_triage_distribution"].pop("mild"), "severity_to_triage_distribution"),
        (lambda d: d["severity_to_triage_distribution"]["mild"].update({"5": 0.9}), "sum to ~1.0"),
        (lambda d: d["arrival_mode_base_distribution"].pop("police"), "arrival_mode_base_distribution"),
        (lambda d: d.pop("arrival_mode_base_distribution"), "arrival_mode_base_distribution"),
    ],
)
def test_validator_rejects_each_broken_section(break_it, message):
    data = _shipped()
    break_it(data)
    with pytest.raises(ValueError, match=message):
        TriageProtocols.model_validate(data)


def test_cached_lru():
    """@lru_cache(maxsize=1) — 2 calls same object."""
    assert load_triage_protocols() is load_triage_protocols()
