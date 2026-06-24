"""Integration tests: Phase 2b clinical scenarios for on_warfarin
medication-physiology coupling.

Scope (pure unit-level via direct helper + derive_lab_values calls;
these stand as integration-marked tests because they exercise the
end-to-end detection → derivation pipeline rather than just one function
in isolation):
  - warfarin patient → INR in therapeutic [2.0, 3.5] band
  - DOAC patient → INR baseline (NOT shifted, faithful to clinical
    practice of not monitoring INR for DOAC)
  - no AC → INR baseline
  - warfarin + DIC compound → INR above therapeutic (over-AC bleeding risk)
"""
from __future__ import annotations

import pytest

from clinosim.modules.physiology.engine import (
    derive_lab_values,
    medication_flags_from_context,
)
from clinosim.types.clinical import PhysiologicalState


@pytest.mark.integration
def test_warfarin_patient_pt_inr_in_therapeutic_band():
    """Detection + derivation pipeline: a patient with warfarin in
    current_medications produces INR in the therapeutic [2.0, 3.5] band."""
    class _P:
        current_medications = ["Warfarin 3mg PO daily"]

    flags = medication_flags_from_context(_P())
    assert flags["on_warfarin"] is True

    state = PhysiologicalState()
    labs = derive_lab_values(state, sex="M", age=70, **flags)
    assert 2.0 <= labs["PT_INR"] <= 3.5, \
        f"INR {labs['PT_INR']} outside therapeutic band"


@pytest.mark.integration
def test_doac_patient_pt_inr_baseline():
    """Detection negative + derivation baseline: an apixaban-only patient
    produces baseline INR (~1.0), NOT therapeutic — INR is not monitored
    for DOAC and our model preserves baseline behavior."""
    class _P:
        current_medications = ["Apixaban 5mg PO BID"]

    flags = medication_flags_from_context(_P())
    assert flags["on_warfarin"] is False

    state = PhysiologicalState()
    labs = derive_lab_values(state, sex="M", age=70, **flags)
    assert labs["PT_INR"] < 1.5, \
        f"DOAC patient INR {labs['PT_INR']} should be baseline"


@pytest.mark.integration
def test_no_anticoagulation_pt_inr_baseline():
    """Patient with no AC: baseline formula path (~1.0 for healthy state)."""
    class _P:
        current_medications = ["Aspirin 100mg", "Metformin 500mg"]

    flags = medication_flags_from_context(_P())
    assert flags["on_warfarin"] is False

    state = PhysiologicalState()
    labs = derive_lab_values(state, sex="M", age=70, **flags)
    assert labs["PT_INR"] < 1.2


@pytest.mark.integration
def test_warfarin_with_dic_above_therapeutic():
    """Warfarin + DIC (severe coagulopathy): INR > 2.7 (compounded effect).
    Clinically: warfarin + DIC raises bleeding risk and INR over-shoot."""
    class _P:
        current_medications = ["Warfarin 3mg"]

    flags = medication_flags_from_context(_P())
    state = PhysiologicalState()
    state.coagulation_status = 0.5
    labs = derive_lab_values(state, sex="M", age=70, **flags)
    assert labs["PT_INR"] > 2.7, \
        "warfarin + DIC should compound to over-therapeutic"
