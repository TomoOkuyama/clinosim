"""Triage level is consistent with the triage vitals, pain and AVPU (#2082)."""

from __future__ import annotations

import pytest

from clinosim.modules.triage.engine import triage_level_cap

pytestmark = pytest.mark.unit


def _vs(**kw) -> dict:
    base = {
        "heart_rate": 80,
        "respiratory_rate": 16,
        "spo2": 98.0,
        "systolic_bp": 125,
        "pain_score": 2,
        "consciousness_level": "A",
    }
    base.update(kw)
    return base


@pytest.mark.parametrize(
    ("vitals", "cap"),
    [
        (_vs(), 5),
        (_vs(consciousness_level="U"), 1),
        (_vs(consciousness_level="P"), 2),
        (_vs(spo2=88.0), 2),
        (_vs(systolic_bp=85), 2),
        (_vs(heart_rate=115), 3),
        (_vs(respiratory_rate=24), 3),
        (_vs(spo2=91.0), 3),
        (_vs(pain_score=8), 3),
        (_vs(consciousness_level=""), 5),
    ],
)
def test_cap_from_vitals(vitals: dict, cap: int) -> None:
    assert triage_level_cap(vitals) == cap


def test_enricher_applies_the_cap() -> None:
    from datetime import datetime
    from types import SimpleNamespace

    from clinosim.modules.triage.engine import triage_enricher

    enc = SimpleNamespace(
        encounter_type="emergency",
        severity="mild",
        encounter_id="E1",
        admission_datetime=datetime(2026, 5, 1, 9),
        chief_complaint="dyspnea",
    )
    vitals = [SimpleNamespace(timestamp=datetime(2026, 5, 1, 9, 10), **_vs(spo2=87.0))]
    record = SimpleNamespace(encounters=[enc], vital_signs=vitals)
    for seed in range(20):
        triage_enricher(SimpleNamespace(config=SimpleNamespace(country="US"), records=[record], master_seed=seed))
        assert int(enc.triage_data.level) <= 2
