"""Test-only forcing of an in-stay complication (Issue #3976).

``ForcedScenario.force_complications`` makes a complication of the disease
protocol fire on a stated hospital day in ``run_forced``. It is read only by
``run_forced``; a scenario without it runs on the cached protocol itself.
"""

from __future__ import annotations

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.simulator.forced_complications import forced_complication_protocol
from clinosim.types.config import ForcedComplication, ForcedScenario


@pytest.mark.unit
def test_unset_returns_the_cached_protocol_itself():
    protocol = load_disease_protocol("bacterial_pneumonia")
    assert forced_complication_protocol(protocol, []) is protocol


@pytest.mark.unit
def test_forced_entry_fires_on_its_day_without_parent_or_risk_factors():
    protocol = load_disease_protocol("bacterial_pneumonia")
    forced = forced_complication_protocol(protocol, [ForcedComplication(name="pulmonary_embolism", day=4)])
    assert forced is not protocol
    entry = next(c for c in forced.complications if c["name"] == "pulmonary_embolism")
    assert entry["onset_day_range"] == [4, 4]
    assert entry["probability_per_day"] == 1.0
    assert "parent_complication" not in entry
    assert entry["risk_factors"] == []
    # The cached protocol is not mutated.
    original = next(c for c in protocol.complications if c["name"] == "pulmonary_embolism")
    assert original.get("parent_complication") == "dvt"
    # The other complications are unchanged.
    others = [c for c in forced.complications if c["name"] != "pulmonary_embolism"]
    assert others == [c for c in protocol.complications if c["name"] != "pulmonary_embolism"]


@pytest.mark.unit
def test_unknown_complication_fails_loud():
    protocol = load_disease_protocol("bacterial_pneumonia")
    with pytest.raises(ValueError, match="no_such_thing"):
        forced_complication_protocol(protocol, [ForcedComplication(name="no_such_thing", day=2)])


@pytest.mark.unit
def test_forced_complication_model_rejects_unknown_keys():
    with pytest.raises(ValueError):
        ForcedComplication(name="dvt", day=3, probability=0.5)
    assert ForcedScenario(disease_id="sepsis").force_complications == []


@pytest.mark.unit
def test_run_forced_fires_the_forced_complication_on_its_day():
    from clinosim.simulator.engine import run_forced
    from clinosim.types.config import SimulatorConfig

    scenario = ForcedScenario(
        disease_id="urinary_tract_infection",
        severity="moderate",
        archetype="smooth_recovery",
        patient_overrides={"age": 70, "sex": "F"},
        force_complications=[ForcedComplication(name="dvt", day=3)],
    )
    record = run_forced(scenario, SimulatorConfig(random_seed=42, country="US")).patients[0]
    onsets = {(c["name"], c["onset_day"]) for c in record.complications_occurred}
    assert ("dvt", 3) in onsets
