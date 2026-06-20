"""Integration test: outpatient/ED HbA1c comes from the glycemic_control physiology
axis (not a flat per-venue baseline constant). Guards DET-6 + the HbA1c model."""

from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.patient.test_patient import create_test_patient
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.staff import StaffRoster


def _hba1c_for_control(glycemic_control: float) -> float:
    patient = create_test_patient()
    dm = next(c for c in patient.chronic_conditions if c.code.startswith("E11"))
    dm.glycemic_control = glycemic_control
    record = _simulate_outpatient_visit(
        patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 6, 1, 9, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(1),
        chronic_code="E11.9",
        followup_spec={"labs": ["HbA1c"]},
        country="US",
    )
    hba1c = [r for r in record.lab_results if r.lab_name == "HbA1c"]
    assert hba1c, "HbA1c should be resulted at an outpatient diabetes follow-up"
    return hba1c[0].value


@pytest.mark.integration
def test_outpatient_hba1c_varies_with_glycemic_control():
    good = _hba1c_for_control(0.9)   # well-controlled
    poor = _hba1c_for_control(0.1)   # poorly-controlled
    assert poor > good, f"poor control HbA1c {poor} should exceed good control {good}"
    # And it is not the old flat 6.5 baseline for both.
    assert not (abs(good - 6.5) < 0.2 and abs(poor - 6.5) < 0.2)
