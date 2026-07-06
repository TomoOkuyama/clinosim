"""FP-ARCH-1: subdural_hematoma has authored course_archetypes + complications.

Previously it fell back to the generic infection-tuned trajectories; it now carries a
post-evacuation neurosurgical course + re-bleed / delirium / herniation / VTE
complications. Risk-factor conditions use only those _evaluate_risk_condition supports
(severity_severe, age_over_N, perfusion_status<X, delirium_susceptibility>X,
immobility_days>N) so none silently no-op.
"""

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol

pytestmark = pytest.mark.unit

_CANONICAL = {
    "smooth_recovery",
    "dip_then_recovery",
    "plateau_then_recovery",
    "treatment_resistant",
    "gradual_deterioration",
    "sudden_deterioration",
}
_SUPPORTED_RISK_PREFIXES = (
    "severity_severe", "age_over_", "renal_function", "volume_status",
    "perfusion_status", "delirium_susceptibility", "immobility_days",
)


def test_subdural_has_course_archetypes():
    p = load_disease_protocol("subdural_hematoma")
    assert set(p.course_archetypes.keys()) == _CANONICAL
    for name, a in p.course_archetypes.items():
        assert "probability" in a and "trajectory" in a, f"{name} incomplete"


def test_subdural_trajectories_use_recognized_state_vars():
    recognized = {
        "anemia_level", "cardiac_function", "coagulation_status", "glucose_status",
        "hepatic_function", "inflammation_level", "perfusion_status", "ph_status",
        "renal_function", "volume_status",
    }
    p = load_disease_protocol("subdural_hematoma")
    for name, a in p.course_archetypes.items():
        for var in a["trajectory"]:
            assert var in recognized, f"{name}: unrecognized trajectory var {var!r}"


def test_subdural_complications_use_supported_risk_conditions():
    p = load_disease_protocol("subdural_hematoma")
    names = {c.get("name") for c in p.complications}
    assert "recurrent_hematoma" in names
    assert any("herniation" in n for n in names if n)
    for c in p.complications:
        for rf in c.get("risk_factors", []):
            cond = rf.get("condition", "")
            assert cond.startswith(_SUPPORTED_RISK_PREFIXES), (
                f"{c.get('name')}: risk condition {cond!r} is not supported by "
                f"_evaluate_risk_condition (would silently no-op)"
            )
