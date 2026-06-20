"""Unit tests for immunization generation."""

import pytest

pytestmark = pytest.mark.unit


def test_types_importable():
    from clinosim.types.encounter import ImmunizationRecord
    r = ImmunizationRecord(vaccine_cvx="150")
    assert r.status == "completed" and r.primary_source is True
