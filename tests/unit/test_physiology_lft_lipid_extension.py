"""Unit tests for LFT (ALP/GGT/TP/LDH) + Lipid (TC/LDL/HDL/TG) derivation.

Issue #1073 B8. Verifies the panel completeness gap fix:
- pre-fix: LFT emitted 2/8 components (only AST+ALT), Lipid emitted 0/4
- post-fix: derive_lab_values produces all 8 additional analytes so the
  panel expander in daily_loop / outpatient can surface them.
"""

from __future__ import annotations

from clinosim.modules.physiology.engine import derive_lab_values, initialize_state
from clinosim.types.patient import PatientPhysiologicalProfile


def _healthy_state():
    """Full-function state (all reserves = 1.0). Baseline derives should
    land within reference range. We explicitly force reserves to 1.0
    because ``PatientPhysiologicalProfile()`` default reserves are drawn
    from a beta distribution that lands ~0.85-0.95, still ostensibly
    healthy but enough to nudge derives outside their narrowest range."""
    profile = PatientPhysiologicalProfile()
    state = initialize_state(profile, [], patient_id="PT-HEALTHY")
    state.hepatic_function = 1.0
    state.renal_function = 1.0
    state.cardiac_function = 1.0
    state.perfusion_status = 1.0
    return state


def _hepatic_impaired_state(fraction: float = 0.4):
    """Hepatic reserve reduced to `fraction` (0.4 = severe hepatic impairment)."""
    state = _healthy_state()
    state.hepatic_function = fraction
    return state


def test_lft_extension_produces_all_four_analytes() -> None:
    labs = derive_lab_values(_healthy_state(), sex="M", age=55)
    for analyte in ("ALP", "GGT", "TP", "LDH"):
        assert analyte in labs, f"{analyte} missing from derive_lab_values output"
        assert labs[analyte] > 0


def test_lipid_extension_produces_all_four_analytes() -> None:
    labs = derive_lab_values(_healthy_state(), sex="M", age=55)
    for analyte in ("TC", "LDL", "HDL", "TG"):
        assert analyte in labs, f"{analyte} missing from derive_lab_values output"
        assert labs[analyte] > 0


def test_healthy_lft_within_reference_range() -> None:
    labs = derive_lab_values(_healthy_state(), sex="M", age=55)
    # JCCLS healthy adult ranges — baseline values sit mid-range.
    assert 40 <= labs["ALP"] <= 130, f"ALP {labs['ALP']} outside 40-130"
    assert 10 <= labs["GGT"] <= 50, f"GGT (M) {labs['GGT']} outside 10-50"
    assert 6.0 <= labs["TP"] <= 8.3, f"TP {labs['TP']} outside 6.0-8.3"
    assert 120 <= labs["LDH"] <= 250, f"LDH {labs['LDH']} outside 120-250"


def test_healthy_lipid_within_normal_band() -> None:
    labs_m = derive_lab_values(_healthy_state(), sex="M", age=55)
    labs_f = derive_lab_values(_healthy_state(), sex="F", age=55)
    assert labs_m["TC"] < 200  # desirable
    assert labs_m["LDL"] < 130  # near-optimal
    assert labs_m["HDL"] >= 40  # male non-risk
    assert labs_f["HDL"] >= 50  # female non-risk
    assert labs_m["TG"] < 150  # normal


def test_hepatic_impairment_elevates_all_lft_analytes() -> None:
    healthy = derive_lab_values(_healthy_state(), sex="M", age=55)
    impaired = derive_lab_values(_hepatic_impaired_state(0.4), sex="M", age=55)
    # All 4 LFT extensions elevate with hepatic dysfunction
    assert impaired["ALP"] > healthy["ALP"]
    assert impaired["GGT"] > healthy["GGT"]
    assert impaired["LDH"] > healthy["LDH"]
    # TP DROPS with hepatic dysfunction (protein synthesis loss)
    assert impaired["TP"] < healthy["TP"]


def test_dyslipidemia_elevates_TC_LDL_TG_drops_HDL() -> None:  # noqa: N802 (clinical acronyms)
    healthy = derive_lab_values(_healthy_state(), sex="M", age=55, has_dyslipidemia=False)
    dyslip = derive_lab_values(_healthy_state(), sex="M", age=55, has_dyslipidemia=True)
    assert dyslip["TC"] > healthy["TC"]
    assert dyslip["LDL"] > healthy["LDL"]
    assert dyslip["TG"] > healthy["TG"]
    assert dyslip["HDL"] < healthy["HDL"]


def test_diabetes_elevates_TG_independently_of_dyslipidemia() -> None:  # noqa: N802 (clinical acronym)
    no_dm = derive_lab_values(_healthy_state(), sex="M", age=55, has_diabetes=False)
    dm = derive_lab_values(_healthy_state(), sex="M", age=55, has_diabetes=True)
    assert dm["TG"] > no_dm["TG"]


def test_hdl_sex_specific_baseline() -> None:
    labs_m = derive_lab_values(_healthy_state(), sex="M", age=55)
    labs_f = derive_lab_values(_healthy_state(), sex="F", age=55)
    # Female HDL baseline > male by ~10 mg/dL
    assert labs_f["HDL"] > labs_m["HDL"]


def test_ggt_sex_specific_baseline() -> None:
    labs_m = derive_lab_values(_healthy_state(), sex="M", age=55)
    labs_f = derive_lab_values(_healthy_state(), sex="F", age=55)
    assert labs_m["GGT"] > labs_f["GGT"]


def test_tp_floor_holds_under_extreme_hepatic_failure() -> None:
    """TP must never dip below the physiologic floor even at hepatic=0."""
    state = _healthy_state()
    state.hepatic_function = 0.0
    labs = derive_lab_values(state, sex="M", age=55)
    from clinosim.modules.physiology._lab_derivation_thresholds import TP_FLOOR_G_DL

    assert labs["TP"] >= TP_FLOOR_G_DL
