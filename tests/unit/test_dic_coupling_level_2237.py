"""DIC coagulopathy tracks the inflammation driver instead of accumulating (Issue #2237)."""

from __future__ import annotations

import pytest

from clinosim.modules.physiology.engine import apply_coupling_rules
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


def _ticks(state: PhysiologicalState, n: int) -> PhysiologicalState:
    for _ in range(n):
        apply_coupling_rules(state)
    return state


def test_dic_plateaus_with_persistent_inflammation() -> None:
    s = PhysiologicalState(inflammation_level=0.9, coagulation_status=0.0)
    after_10 = _ticks(s, 10).coagulation_status
    after_100 = _ticks(s, 90).coagulation_status
    assert after_10 > 0
    assert after_100 == pytest.approx(after_10)  # a level, not a running sum


def test_dic_level_does_not_depend_on_tick_rate() -> None:
    hourly = _ticks(PhysiologicalState(inflammation_level=0.95), 24).coagulation_status
    daily = _ticks(PhysiologicalState(inflammation_level=0.95), 1).coagulation_status
    assert hourly == pytest.approx(daily)


def test_severe_inflammation_still_produces_meaningful_coagulopathy() -> None:
    assert _ticks(PhysiologicalState(inflammation_level=1.0), 1).coagulation_status >= 0.25


def test_existing_coagulopathy_is_not_reduced_by_coupling() -> None:
    s = _ticks(PhysiologicalState(inflammation_level=0.75, coagulation_status=0.8), 5)
    assert s.coagulation_status == pytest.approx(0.8)


def test_hepatic_coagulopathy_is_a_level_too() -> None:
    s = PhysiologicalState(hepatic_function=0.2, coagulation_status=0.0)
    first = _ticks(s, 1).coagulation_status
    assert first > 0 and _ticks(s, 50).coagulation_status == pytest.approx(first)


def test_disease_yamls_raise_coagulation_status_for_coagulopathy() -> None:
    """``coagulation_status`` is 0 = normal, higher = coagulopathy. An initial
    impact or a complication that makes it negative only clamps at 0 and
    silently does nothing; sepsis and decompensated cirrhosis had the sign
    inverted (Issue #2237)."""
    from pathlib import Path

    import yaml

    bad = []
    for path in sorted(Path("clinosim/modules/disease/reference_data").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for sev, impact in (data.get("initial_state_impact") or {}).items():
            if (impact or {}).get("coagulation_status", 0) < 0:
                bad.append(f"{path.name} initial_state_impact.{sev}")
        for comp in data.get("complications") or []:
            if (comp.get("state_impact") or {}).get("coagulation_status", 0) < 0:
                bad.append(f"{path.name} complication {comp.get('name')}")
    assert not bad, bad
