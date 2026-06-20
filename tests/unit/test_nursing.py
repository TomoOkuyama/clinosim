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
