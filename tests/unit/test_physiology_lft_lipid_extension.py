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


def test_ldl_is_friedewald_consistent_when_tg_below_400() -> None:  # noqa: N802
    """C5 / #1091: LDL must be internally consistent with TC/HDL/TG.

    Friedewald: LDL = TC - HDL - TG/5 (all mg/dL, valid when TG < 400).
    The pre-C5 physiology computed LDL from an independent formula on
    E78, giving LDL values that could disagree with TC-HDL-TG by tens of
    mg/dL. That's not just a LOINC-selection defect (2089-1 vs 13457-7)
    but an internal-consistency defect: consumers computing LDL from the
    other three saw a different number from what we emitted.
    """
    for sex in ("M", "F"):
        for has_dyslip in (False, True):
            labs = derive_lab_values(
                _healthy_state(),
                sex=sex,
                age=55,
                has_dyslipidemia=has_dyslip,
            )
            # Only assert when TG < 400 (Friedewald validity range)
            if labs["TG"] >= 400:
                continue
            expected = labs["TC"] - labs["HDL"] - labs["TG"] / 5
            assert abs(labs["LDL"] - expected) < 1.0, (
                f"sex={sex} dyslip={has_dyslip}: "
                f"LDL={labs['LDL']:.1f} but Friedewald(TC={labs['TC']:.1f}, "
                f"HDL={labs['HDL']:.1f}, TG={labs['TG']:.1f}) = {expected:.1f}"
            )


def test_ldl_floor_at_healthy_low_bound() -> None:  # noqa: N802
    """Even with high HDL / low TC, LDL floors at a plausible low bound
    (≥ 30 mg/dL) — no negative values from the Friedewald subtraction."""
    labs = derive_lab_values(_healthy_state(), sex="F", age=55)
    assert labs["LDL"] >= 30.0, labs


def test_us_ldl_loinc_is_13457_7_calc_not_2089_1_generic() -> None:  # noqa: N802
    """C5 / #1091: US LDL now emits LOINC 13457-7 (calc-Friedewald).

    2089-1 (\"Cholesterol in LDL [Mass/volume] in Serum or Plasma\") is
    the older generic code; 13457-7 (\"…by calculation\") is the modern
    preferred code that also matches how we now derive LDL. Pin the
    mapping so a future YAML edit that reverts to 2089-1 fails loud.
    """
    from pathlib import Path

    import yaml

    mapping_path = Path(__file__).resolve().parents[2] / "clinosim" / "locale" / "us" / "code_mapping_lab.yaml"
    with mapping_path.open(encoding="utf-8") as fh:
        mapping = yaml.safe_load(fh)
    assert mapping.get("LDL") == "13457-7", (
        f"US LDL LOINC should be 13457-7 (calc-Friedewald); got {mapping.get('LDL')!r}"
    )


def test_tp_floor_holds_under_extreme_hepatic_failure() -> None:
    """TP must never dip below the physiologic floor even at hepatic=0."""
    state = _healthy_state()
    state.hepatic_function = 0.0
    labs = derive_lab_values(state, sex="M", age=55)
    from clinosim.modules.physiology._lab_derivation_thresholds import TP_FLOOR_G_DL

    assert labs["TP"] >= TP_FLOOR_G_DL
