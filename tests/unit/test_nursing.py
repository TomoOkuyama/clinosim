"""Unit tests for nursing flowsheet scores."""

import pytest

pytestmark = pytest.mark.unit


def test_types_importable():
    from clinosim.types.encounter import NursingRiskAssessment, VitalSignRecord

    v = VitalSignRecord()
    assert v.news2_score is None and v.gcs_score is None
    n = NursingRiskAssessment()
    assert 6 <= n.braden_total <= 23
    assert n.fall_risk_level == "low"


def test_news2_normal_is_zero():
    from clinosim.modules.observation.nursing import compute_news2

    vs = {
        "respiratory_rate": 16,
        "spo2": 98,
        "on_supplemental_oxygen": False,
        "temperature_celsius": 36.8,
        "systolic_bp": 120,
        "heart_rate": 70,
        "consciousness_level": "A",
    }
    assert compute_news2(vs) == 0


def test_news2_aggregates_known_case():
    from clinosim.modules.observation.nursing import compute_news2

    # RR 26 (+3), SpO2 92 (+2), on O2 (+2), Temp 39.2 (+2), SBP 95 (+2),
    # HR 115 (+2), AVPU A (0) = 13
    vs = {
        "respiratory_rate": 26,
        "spo2": 92,
        "on_supplemental_oxygen": True,
        "temperature_celsius": 39.2,
        "systolic_bp": 95,
        "heart_rate": 115,
        "consciousness_level": "A",
    }
    assert compute_news2(vs) == 13


def _rng():
    import numpy as np

    return np.random.default_rng(42)


def test_gcs_avpu_bands_in_range():
    from clinosim.modules.observation.nursing import compute_gcs

    for loc in ("A", "V", "P", "U"):
        g = compute_gcs(loc, perfusion_status=1.0, rng=_rng())
        assert 3 <= g <= 15
    assert compute_gcs("A", 1.0, _rng()) >= compute_gcs("U", 1.0, _rng())


def test_braden_total_in_range_and_monotone():
    from clinosim.modules.observation.nursing import compute_braden

    healthy = compute_braden({"barthel_score": 100}, "A", 0.0, _rng())
    frail = compute_braden({"barthel_score": 10}, "P", 0.5, _rng())
    assert 6 <= frail["braden_total"] <= healthy["braden_total"] <= 23
    assert healthy["braden_total"] >= 20  # robust patient: high Braden
    assert frail["braden_total"] <= 14  # frail patient: low Braden (high risk)


def test_morse_levels():
    from clinosim.modules.observation.nursing import compute_morse_fall_risk

    score, level = compute_morse_fall_risk(85, {"barthel_score": 20}, "P", True, _rng())
    assert 0 <= score <= 125 and level in ("low", "moderate", "high")


def test_deterministic_same_seed():
    import numpy as np

    from clinosim.modules.observation.nursing import compute_braden

    a = compute_braden({"barthel_score": 50}, "A", 0.0, np.random.default_rng(7))
    b = compute_braden({"barthel_score": 50}, "A", 0.0, np.random.default_rng(7))
    assert a == b


def test_braden_reaches_published_floor_for_unresponsive_dependent_patient():
    """Braden subscales must reach their full published low end (severe-risk
    range) for a fully dependent, unresponsive, incontinent patient — before
    this fix, sensory/moisture/friction were binary and never dropped below
    ~10-11 total (2026-06-20 realism audit finding)."""
    from clinosim.modules.observation.nursing import compute_braden

    critical = compute_braden({"barthel_score": 0}, "U", 0.8, _rng())
    assert critical["braden_sensory"] == 1
    assert critical["braden_moisture"] == 1
    assert critical["braden_friction"] == 1
    assert critical["braden_total"] == 6
