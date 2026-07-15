"""Integration tests: anion_gap_status axis via encounter YAML initial_state_impact.

Companion to test_sodium_axis.py. GI conditions (viral gastroenteritis, food
poisoning) declare a NEGATIVE anion_gap_status in initial_state_impact to model
non-anion-gap (hyperchloremic) metabolic acidosis from stool bicarbonate loss —
"Severity scales with stool volume" per the YAML author. The axis routes the HCO3
deficit onto Cl (electroneutrality) in derive_lab_values.

Regression guard: apply_disease_onset must NOT clamp the negative axis to 0.0.
Before the _variable_range fix, anion_gap_status was missing from the range table
and fell back to (0.0, 1.0), collapsing every GI severity to 0.0 (degenerate).
"""

import pytest

from clinosim.modules.physiology.engine import (
    apply_disease_onset,
    derive_lab_values,
)
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.integration


def test_gi_negative_anion_gap_is_preserved_not_clamped() -> None:
    """viral_gastroenteritis's severity-graded negative AG must survive onset."""
    from clinosim.modules.encounter.protocol import load_encounter_condition

    proto = load_encounter_condition("viral_gastroenteritis")
    impact = proto["initial_state_impact"]

    s_mild = apply_disease_onset(PhysiologicalState(renal_function=1.0), "mild", impact)
    s_severe = apply_disease_onset(PhysiologicalState(renal_function=1.0), "severe", impact)

    # The axis is negative (non-AG acidosis) and NOT clamped to zero.
    assert s_mild.anion_gap_status < 0.0, s_mild.anion_gap_status
    assert s_severe.anion_gap_status < 0.0, s_severe.anion_gap_status
    # Severity is graded: severe stool loss is a more negative AG than mild.
    assert s_severe.anion_gap_status < s_mild.anion_gap_status


def test_negative_anion_gap_amplifies_hyperchloremia() -> None:
    """A negative AG must raise Cl ABOVE the anion_gap_status==0 baseline.

    This is the sharp clamp regression guard: before the fix the negative axis
    collapsed to 0.0, so a GI patient produced the SAME Cl as a neutral-axis
    patient. non_ag_fraction goes 1.0 -> 1.5 as the axis goes 0.0 -> -0.6.
    """
    # A metabolic-acidosis state with a real HCO3 deficit (ph_status < 0).
    base = dict(renal_function=1.0, ph_status=-0.4)

    s_neutral = apply_disease_onset(PhysiologicalState(**base), "x", {"x": {"anion_gap_status": 0.0}})
    s_non_ag = apply_disease_onset(PhysiologicalState(**base), "x", {"x": {"anion_gap_status": -0.6}})

    cl_neutral = derive_lab_values(s_neutral, sex="M", age=40)["Cl"]
    cl_non_ag = derive_lab_values(s_non_ag, sex="M", age=40)["Cl"]

    # Non-AG (GI loss) drives Cl strictly higher than the neutral axis; the clamp
    # bug erased this separation entirely.
    assert cl_non_ag > cl_neutral + 1.0, (cl_non_ag, cl_neutral)
