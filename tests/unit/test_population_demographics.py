"""Unit tests for externalized population demographics."""

import numpy as np
import pytest

from clinosim.modules.population.engine import PersonRecord


def test_person_record_has_lifestyle_fields():
    """PersonRecord must carry bmi, smoking_status, alcohol_use for Layer-1 risk use."""
    p = PersonRecord(person_id="POP-001", household_id="HH-001", age=45, sex="M", date_of_birth=None)
    assert hasattr(p, "bmi"), "bmi field missing from PersonRecord"
    assert hasattr(p, "smoking_status"), "smoking_status field missing"
    assert hasattr(p, "alcohol_use"), "alcohol_use field missing"
    assert isinstance(p.bmi, float)
    assert p.smoking_status in ("never", "former", "current")
    assert p.alcohol_use in ("none", "social", "heavy")
