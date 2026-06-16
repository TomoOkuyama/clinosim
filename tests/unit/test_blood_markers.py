"""Unit tests for cardiac injury markers (Troponin_I, CK_MB) — clinical consistency (AD-55)."""

from __future__ import annotations

import pytest

from clinosim.modules.observation.engine import canonical_lab_name, determine_flag
from clinosim.modules.physiology.engine import derive_lab_values
from clinosim.types.clinical import PhysiologicalState


def _state(cardiac: float, renal: float = 1.0) -> PhysiologicalState:
    return PhysiologicalState(cardiac_function=cardiac, renal_function=renal)


@pytest.mark.unit
class TestTroponinDerivation:
    def test_normal_heart_negative(self):
        labs = derive_lab_values(_state(1.0), sex="M", age=60)
        assert labs["Troponin_I"] < 0.04  # negative rule-out

    def test_acs_strongly_elevated(self):
        labs = derive_lab_values(_state(0.4), sex="M", age=65, myocardial_injury=True)
        assert labs["Troponin_I"] > 10.0  # MI-level
        assert labs["CK_MB"] > 5.0

    def test_noncardiac_dysfunction_only_mild(self):
        # Septic cardiac depression (low cardiac) WITHOUT myocardial injury → mild type-2.
        labs = derive_lab_values(_state(0.4), sex="M", age=65, myocardial_injury=False)
        assert labs["Troponin_I"] < 5.0  # not MI-level
        # ...and far below what ACS would produce at the same cardiac function
        acs = derive_lab_values(_state(0.4), sex="M", age=65, myocardial_injury=True)
        assert acs["Troponin_I"] > 10 * labs["Troponin_I"]

    def test_ckd_confounder(self):
        # CKD (low renal) with a normal heart → mild elevation (reduced clearance).
        normal = derive_lab_values(_state(1.0, renal=1.0), sex="M", age=70)
        ckd = derive_lab_values(_state(1.0, renal=0.3), sex="M", age=70)
        assert ckd["Troponin_I"] > normal["Troponin_I"]
        assert ckd["Troponin_I"] < 0.5  # mild, not MI-level

    def test_graded_with_severity(self):
        mild = derive_lab_values(_state(0.6), sex="M", age=65, myocardial_injury=True)
        severe = derive_lab_values(_state(0.3), sex="M", age=65, myocardial_injury=True)
        assert severe["Troponin_I"] > mild["Troponin_I"]


@pytest.mark.unit
class TestFlagAndCanonical:
    def test_sex_specific_cutoff(self):
        # 0.035 ng/mL: above female cutoff (0.03), at/below male cutoff (0.04)
        assert determine_flag("Troponin_I", 0.035, sex="F") == "H"
        assert determine_flag("Troponin_I", 0.035, sex="M") is None

    def test_canonical_lab_name(self):
        assert canonical_lab_name("Troponin") == "Troponin_I"
        assert canonical_lab_name("Troponin_I_stat") == "Troponin_I"
        assert canonical_lab_name("Troponin_I_serial_6h") == "Troponin_I"
        assert canonical_lab_name("Troponin_repeat") == "Troponin_I"
        assert canonical_lab_name("CRP") == "CRP"  # non-aliased unchanged
        assert canonical_lab_name("CK_MB") == "CK_MB"
