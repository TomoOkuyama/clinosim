"""Integration tests: sodium_status drivers via disease YAML initial_state_impact.

Task 3 of 4 — verify that HF exacerbation (acute fluid overload) and bacterial
pneumonia (SIADH) both lower sodium on admission through the data-driven YAML path.
No engine if-branches required: apply_disease_onset generically applies every key
in initial_state_impact to the matching state field.
"""

import pytest

pytestmark = pytest.mark.integration


def test_hf_exacerbation_lowers_sodium() -> None:
    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.modules.physiology.engine import apply_disease_onset, derive_lab_values
    from clinosim.types.clinical import PhysiologicalState

    p = load_disease_protocol("heart_failure_exacerbation")
    s = PhysiologicalState(renal_function=1.0)
    s = apply_disease_onset(s, "severe", p.initial_state_impact)
    assert s.sodium_status < 0, f"Expected sodium_status < 0, got {s.sodium_status}"
    na = derive_lab_values(s, sex="M", age=60)["Na"]
    assert na < 138, f"Expected Na < 138 (hyponatremia), got {na}"


def test_pneumonia_siadh_lowers_sodium() -> None:
    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.modules.physiology.engine import apply_disease_onset, derive_lab_values
    from clinosim.types.clinical import PhysiologicalState

    p = load_disease_protocol("bacterial_pneumonia")
    s = PhysiologicalState(renal_function=1.0)
    s = apply_disease_onset(s, "severe", p.initial_state_impact)
    assert s.sodium_status < 0, f"Expected sodium_status < 0, got {s.sodium_status}"
    na = derive_lab_values(s, sex="M", age=60)["Na"]
    assert na < 139, f"Expected Na < 139 (hyponatremia), got {na}"
