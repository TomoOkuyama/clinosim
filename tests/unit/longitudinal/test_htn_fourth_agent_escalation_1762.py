"""Issue #1762 — HTN 4th-agent treatment escalation event.

The 3rd-agent event (htn_escalate_third_agent_i10) is one-shot; patients
whose SBP remains > 150 after it fires received no further escalation
(650 patients in US p=10k seed=42 5y cohort). This file ships the
4th-line event (adds Spironolactone per PATHWAY-2 / ACC-AHA 2017) and
tests the fire/no-fire gating + the chronic_medications.yaml activation
guard that keeps the initial-cohort sampler from picking Spironolactone.
"""

from __future__ import annotations

import numpy as np
import pytest
import yaml

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.patterns.event import step

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Attribute spec loads correctly
# ---------------------------------------------------------------------------


def test_fourth_agent_event_registered_in_catalog():
    specs = load_attribute_specs()
    assert "htn_escalate_fourth_agent_i10" in specs, (
        "clinosim/locale/shared/longitudinal/med/htn_escalate_fourth_agent_i10.yaml "
        "must be loaded by load_attribute_specs()"
    )


def test_fourth_agent_event_emits_spironolactone():
    specs = load_attribute_specs()
    spec = specs["htn_escalate_fourth_agent_i10"]
    assert spec.body.emits_meds == ["Spironolactone"], (
        f"4th-agent event must emit Spironolactone (MRA, resistant-HTN "
        f"4th-line per ACC-AHA 2017). Got: {spec.body.emits_meds}"
    )
    assert spec.body.fire_marker == "htn_escalate_fourth_agent_i10"
    assert spec.body.one_shot is True


# ---------------------------------------------------------------------------
# Rate gating: SBP > 150 fires, SBP <= 150 does not
# ---------------------------------------------------------------------------


def test_fires_when_sbp_above_150():
    """2000 trials, SBP=180, base_rate=0.30 → fires ~600 times
    (within a wide tolerance)."""
    specs = load_attribute_specs()
    spec = specs["htn_escalate_fourth_agent_i10"]
    rng = np.random.default_rng(42)
    fires = 0
    for _ in range(2000):
        result = step(
            ["I10"],
            [],
            rng,
            spec.body,
            context={"age": 60, "continuous": {"sbp": 180.0}, "chronic_conditions": ["I10"]},
        )
        if result.fired:
            fires += 1
    # 0.30 * 2000 = 600 expected; 2-sigma binomial ~ ±43. 450-750 is a
    # wide-enough band that normal RNG variance doesn't flap.
    assert 450 < fires < 750, f"expected ~600 fires at SBP=180, base_rate=0.30; got {fires}"


def test_does_not_fire_when_sbp_at_or_below_150():
    """The ``sbp <= 150`` rate_modifier zeros the rate; 2000 trials → 0 fires."""
    specs = load_attribute_specs()
    spec = specs["htn_escalate_fourth_agent_i10"]
    rng = np.random.default_rng(42)
    fires = 0
    for _ in range(2000):
        result = step(
            ["I10"],
            [],
            rng,
            spec.body,
            context={"age": 60, "continuous": {"sbp": 148.0}, "chronic_conditions": ["I10"]},
        )
        if result.fired:
            fires += 1
    assert fires == 0, f"expected 0 fires at SBP=148 (<=150 gate), got {fires}"


def test_one_shot_dedup_against_prior_fire():
    """The event is one-shot. A patient with the fire_marker already in
    a prior-year's med_additions must not re-fire regardless of SBP."""

    class _Snap:
        def __init__(self, med_additions):
            self.med_additions = med_additions
            self.new_complications: list[str] = []

    specs = load_attribute_specs()
    spec = specs["htn_escalate_fourth_agent_i10"]
    rng = np.random.default_rng(42)
    prior = [_Snap(["htn_escalate_fourth_agent_i10"])]
    for _ in range(500):
        result = step(
            ["I10"],
            prior,
            rng,
            spec.body,
            context={"age": 60, "continuous": {"sbp": 190.0}, "chronic_conditions": ["I10"]},
        )
        assert not result.fired, "fire_marker dedup must suppress re-fire"


# ---------------------------------------------------------------------------
# Activation sampler guard: Spironolactone has probability: 0.0 on I10
# ---------------------------------------------------------------------------


def test_spironolactone_registered_in_i10_with_zero_probability():
    """``chronic_medications.yaml::I10`` must list Spironolactone with
    ``probability: 0.0`` so the initial-cohort activation sampler never
    picks it — the drug is reserved for the longitudinal engine's
    4th-agent event (same pattern as HCTZ for the 3rd agent)."""
    import pathlib

    yaml_path = (
        pathlib.Path(__file__).resolve().parents[3] / "clinosim" / "locale" / "shared" / "chronic_medications.yaml"
    )
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    i10_meds = (data.get("I10") or {}).get("medications") or []
    spiro = next((m for m in i10_meds if (m.get("drug") or "").lower() == "spironolactone"), None)
    assert spiro is not None, "I10 chronic_medications block must list Spironolactone"
    assert float(spiro.get("probability", 1.0)) == 0.0, (
        f"Spironolactone must carry probability: 0.0 to keep the "
        f"activation sampler from picking it. Got: {spiro.get('probability')}"
    )
    assert spiro.get("drug_class") == "diuretic.k_sparing"
