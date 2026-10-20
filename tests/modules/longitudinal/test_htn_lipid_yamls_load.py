"""Phase 4b.1 — HTN + lipid escalation event yamls load.

Loader picks up all three new event-pattern yamls under
clinosim/locale/shared/longitudinal/med/; step() respects the HbA1c-
analog rate_modifiers (SBP / LDL gates).
"""

from __future__ import annotations

import numpy as np

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.patterns.event import step


def test_htn_escalation_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "htn_escalate_third_agent_i10" in specs
    spec = specs["htn_escalate_third_agent_i10"]
    assert spec.pattern == "event"
    assert spec.depends_on == ["sbp"]
    body = spec.body
    assert body.emits_icd == ""
    assert body.emits_meds == ["Hydrochlorothiazide"]
    assert body.fire_marker == "htn_escalate_third_agent_i10"
    assert body.base_annual_rate == 0.55
    assert body.one_shot is True
    assert spec.clinical_scope.requires_chronic_codes == ["I1"]


def test_htn_escalation_fires_at_sbp_above_140():
    """Rate modifier gates OUT at SBP ≤ 140 (ACC-AHA 2017 third-agent threshold)."""
    load_attribute_specs.cache_clear()
    spec = load_attribute_specs()["htn_escalate_third_agent_i10"].body
    # Controlled (SBP=135) — must NOT fire.
    r = step([], [], np.random.default_rng(0), spec, context={"continuous": {"sbp": 135.0}})
    assert not r.fired
    # Uncontrolled (SBP=145) — fires at base_annual_rate 0.55.
    # seed=2 draws ~0.274 which is < 0.55 so the fire path is exercised.
    r = step([], [], np.random.default_rng(2), spec, context={"continuous": {"sbp": 145.0}})
    assert r.fired
    assert r.med_additions == ["Hydrochlorothiazide"]
