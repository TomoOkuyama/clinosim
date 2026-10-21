"""Phase 1 of Issue #1698 — engine chronic_visit dispatcher wires fan-out.

Final-review Critical: the fan-out guard originally gated on
`event.event_type == "chronic_followup"` but the LifeEvent emitter sets
`event_type="chronic_visit"` (with "chronic_followup" as a sibling
`condition_type` field). Dead code until this test catches it.

The test runs a tiny cohort with a controlled C-code patient and asserts
at least one `department_id="oncology"` encounter lands on the records
list via the engine's healthcare_calendar dispatch path.
"""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_specialty_routing

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clear() -> None:
    load_specialty_routing.cache_clear()
    yield
    load_specialty_routing.cache_clear()


def test_engine_actually_calls_specialty_fanout_tick(monkeypatch) -> None:
    """A p=100 US seed=42 2y cohort must trigger the engine's fan-out
    gate at least once — proven by monkey-patching
    `_specialty_fanout_tick` and asserting the spy counter > 0.

    Direct encounter-count assertion is unreliable here: C-codes already
    route to the `oncology` dept via `_CHRONIC_DISEASE_SPECIALTY` in
    `outpatient_dept.py`, so simply counting oncology encounters cannot
    distinguish fan-out vs the pre-existing routing. The spy call-count
    is what pins the engine gate behaviour.
    """
    import clinosim.simulator.outpatient as outpatient_module

    call_count = {"n": 0}
    original = outpatient_module._specialty_fanout_tick

    def _spy(patient, when):
        call_count["n"] += 1
        return original(patient, when)

    monkeypatch.setattr(outpatient_module, "_specialty_fanout_tick", _spy)

    from clinosim.simulator.engine import run_beta
    from clinosim.types.config import SimulatorConfig

    cfg = SimulatorConfig(
        country="US",
        random_seed=42,
        catchment_population=100,
        time_range=("2024-01-01", "2025-12-31"),
    )
    run_beta(cfg)
    assert call_count["n"] > 0, (
        "engine's chronic_visit dispatcher never called _specialty_fanout_tick — "
        "the fan-out gate uses the wrong event.event_type string"
    )
