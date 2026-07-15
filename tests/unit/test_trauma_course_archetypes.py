"""FP-ARCH-2/3: the 7 remaining trauma/surgical diseases have authored course_archetypes
+ complications (was the generic infection-tuned fallback — clinically wrong for post-op
recovery). Guards the whole batch: canonical archetypes, recognized trajectory state vars,
and complication risk conditions restricted to those _evaluate_risk_condition supports.
"""

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol

pytestmark = pytest.mark.unit

_TRAUMA = [
    "hip_fracture",
    "fall_from_height",
    "traffic_accident_severe",
    "industrial_burn_severe",
    "crush_injury_hand",
    "electrical_injury",
    "wrist_fracture_surgical",
]
_CANONICAL = {
    "smooth_recovery",
    "dip_then_recovery",
    "plateau_then_recovery",
    "treatment_resistant",
    "gradual_deterioration",
    "sudden_deterioration",
}
_RECOGNIZED_VARS = {
    "anemia_level",
    "cardiac_function",
    "coagulation_status",
    "glucose_status",
    "hepatic_function",
    "inflammation_level",
    "perfusion_status",
    "ph_status",
    "renal_function",
    "volume_status",
}
# risk_factor conditions _evaluate_risk_condition actually supports (else silent no-op)
_SUPPORTED_RISK_PREFIXES = (
    "severity_severe",
    "age_over_",
    "renal_function",
    "volume_status",
    "perfusion_status",
    "delirium_susceptibility",
    "immobility_days",
)


@pytest.mark.parametrize("disease_id", _TRAUMA)
def test_trauma_has_canonical_course_archetypes(disease_id):
    p = load_disease_protocol(disease_id)
    assert set(p.course_archetypes.keys()) == _CANONICAL, disease_id
    total = sum(a["probability"] for a in p.course_archetypes.values())
    assert abs(total - 1.0) < 1e-6, f"{disease_id}: archetype probs sum to {total}"


@pytest.mark.parametrize("disease_id", _TRAUMA)
def test_trauma_trajectories_use_recognized_vars(disease_id):
    p = load_disease_protocol(disease_id)
    for name, a in p.course_archetypes.items():
        assert "trajectory" in a, f"{disease_id}/{name} missing trajectory"
        for var in a["trajectory"]:
            assert var in _RECOGNIZED_VARS, f"{disease_id}/{name}: bad var {var!r}"


@pytest.mark.parametrize("disease_id", _TRAUMA)
def test_trauma_complications_supported_and_present(disease_id):
    p = load_disease_protocol(disease_id)
    assert p.complications, f"{disease_id}: no complications"
    for c in p.complications:
        for rf in c.get("risk_factors", []):
            cond = rf.get("condition", "")
            assert cond.startswith(_SUPPORTED_RISK_PREFIXES), (
                f"{disease_id}/{c.get('name')}: risk condition {cond!r} unsupported "
                f"by _evaluate_risk_condition (silent no-op)"
            )
