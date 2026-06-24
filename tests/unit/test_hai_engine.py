"""Unit tests for clinosim.modules.hai.engine (PR-B)."""
from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.hai.engine import (
    _add_days,
    _sample_organism,
    load_hai_codes,
    load_hai_organisms,
    load_hai_rates,
    load_hai_specimens,
    sample_hai_onset,
)
from clinosim.types.device import DeviceRecord


pytestmark = pytest.mark.unit


def test_load_hai_rates_returns_three_types():
    cfg = load_hai_rates()
    assert set(cfg["hai_rates"].keys()) == {"clabsi", "cauti", "vap"}
    assert cfg["hai_rates"]["clabsi"]["per_day_risk"] == 0.0010


def test_load_hai_codes_has_us_jp_snomed_keys():
    cfg = load_hai_codes()
    for hai_type in ("clabsi", "cauti", "vap"):
        entry = cfg["hai_codes"][hai_type]
        assert entry["icd10_us_billable"]
        assert entry["icd10_jp_who"]
        assert entry["snomed"]
        assert entry["display_en"]
        assert entry["display_ja"]


def test_load_hai_organisms_weights_sum_to_one_per_type():
    cfg = load_hai_organisms()
    for hai_type in ("clabsi", "cauti", "vap"):
        ws = [e["weight"] for e in cfg["hai_organisms"][hai_type]]
        total = sum(ws)
        assert abs(total - 1.0) < 1e-3, f"{hai_type} weights sum to {total}, not 1.0"


def test_load_hai_specimens_three_types():
    cfg = load_hai_specimens()
    assert cfg["hai_specimens"]["clabsi"]["specimen"] == "blood"
    assert cfg["hai_specimens"]["cauti"]["specimen"] == "urine"
    assert cfg["hai_specimens"]["vap"]["specimen"] == "sputum"


def test_sample_hai_onset_returns_false_for_short_line_days():
    device = DeviceRecord(
        device_id="d", encounter_id="e", device_type="cvc",
        snomed_code="52124006", placement_date="2026-01-01",
        removal_date="2026-01-02", placement_indication="severity_moderate_plus",
    )
    occurred, _ = sample_hai_onset(device, {"per_day_risk": 0.5}, np.random.default_rng(42))
    assert occurred is False


def test_sample_hai_onset_returns_true_for_long_line_days_high_risk():
    device = DeviceRecord(
        device_id="d", encounter_id="e", device_type="cvc",
        snomed_code="52124006", placement_date="2026-01-01",
        removal_date="2026-12-31", placement_indication="severity_moderate_plus",
    )
    occurred, offset = sample_hai_onset(device, {"per_day_risk": 0.5}, np.random.default_rng(42))
    assert occurred is True
    assert offset is not None
    assert offset >= 2


def test_sample_hai_onset_snapshot_in_progress_uses_fallback():
    """removal_date=None → conservative line_days=7."""
    device = DeviceRecord(
        device_id="d", encounter_id="e", device_type="cvc",
        snomed_code="52124006", placement_date="2026-01-01",
        removal_date=None, placement_indication="severity_moderate_plus",
    )
    occurred_count = 0
    for seed in range(100):
        o, _ = sample_hai_onset(device, {"per_day_risk": 0.5}, np.random.default_rng(seed))
        if o:
            occurred_count += 1
    # With per_day_risk=0.5 over 7 days, cumulative ≈ 0.992 → >=90%
    assert occurred_count >= 90


def test_sample_organism_weighted_distribution_converges():
    weights = [
        {"snomed": "AAA", "weight": 0.5},
        {"snomed": "BBB", "weight": 0.3},
        {"snomed": "CCC", "weight": 0.2},
    ]
    rng = np.random.default_rng(42)
    counts = {"AAA": 0, "BBB": 0, "CCC": 0}
    for _ in range(10000):
        choice = _sample_organism(weights, rng)
        counts[choice] += 1
    assert abs(counts["AAA"] / 10000 - 0.5) < 0.03
    assert abs(counts["BBB"] / 10000 - 0.3) < 0.03
    assert abs(counts["CCC"] / 10000 - 0.2) < 0.03


def test_add_days_iso_string():
    assert _add_days("2026-01-01", 5) == "2026-01-06"
    assert _add_days("2026-01-31", 1) == "2026-02-01"
