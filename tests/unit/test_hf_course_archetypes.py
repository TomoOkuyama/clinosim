"""FP-ARCH-1: heart_failure_exacerbation has authored course_archetypes + complications.

Previously HF fell back to the generic infection-tuned _FALLBACK_TRAJECTORIES; it now
carries a diuresis-driven course + cardiorenal/arrhythmia/shock complications.
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


def test_hf_has_course_archetypes():
    p = load_disease_protocol("heart_failure_exacerbation")
    assert set(p.course_archetypes.keys()) == _CANONICAL
    for name, a in p.course_archetypes.items():
        assert "probability" in a, f"{name} missing probability"
        assert "trajectory" in a, f"{name} missing trajectory"


def test_hf_trajectories_use_recognized_state_vars():
    recognized = {
        "anemia_level", "cardiac_function", "coagulation_status", "glucose_status",
        "hepatic_function", "inflammation_level", "perfusion_status", "ph_status",
        "renal_function", "volume_status",
    }
    p = load_disease_protocol("heart_failure_exacerbation")
    for name, a in p.course_archetypes.items():
        for var in a["trajectory"]:
            assert var in recognized, f"{name}: unrecognized trajectory var {var!r}"


def test_hf_smooth_recovery_diuresis_lowers_volume():
    # The volume_status trajectory of smooth_recovery must be net-negative (diuresis),
    # unlike the generic fallback (which is volume-neutral/positive).
    p = load_disease_protocol("heart_failure_exacerbation")
    vol = p.course_archetypes["smooth_recovery"]["trajectory"]["volume_status"]
    assert sum(vol.values()) < 0, f"smooth_recovery volume_status not net-diuretic: {vol}"


def test_hf_has_complications():
    p = load_disease_protocol("heart_failure_exacerbation")
    names = {c.get("name") for c in p.complications}
    assert "acute_kidney_injury" in names
    assert any("shock" in n or "respiratory_failure" in n for n in names if n)
