"""Surgery raises pain on the operative day (#2080)."""

from __future__ import annotations

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.simulator.daily_loop import apply_postoperative_pain
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


def test_operative_day_sets_pain_floor() -> None:
    state = PhysiologicalState(pain_level=0.3)
    apply_postoperative_pain(state, day=1, surgery=(1, 0.7))
    assert state.pain_level == 0.7
    apply_postoperative_pain(state, day=2, surgery=(1, 0.7))
    assert state.pain_level == 0.7  # only the operative day
    higher = PhysiologicalState(pain_level=0.9)
    apply_postoperative_pain(higher, day=1, surgery=(1, 0.7))
    assert higher.pain_level == 0.9


@pytest.mark.parametrize(
    "disease_id",
    ["hip_fracture", "elective_knee_arthroplasty", "acute_appendicitis", "acute_cholecystitis", "subdural_hematoma"],
)
def test_surgical_protocols_declare_postoperative_pain(disease_id: str) -> None:
    level = (load_disease_protocol(disease_id).procedure or {}).get("postoperative_pain_level")
    assert level is not None and 0.3 <= level <= 0.9
