"""Integration test: Coag panel (LOINC 24373-3) analyte emission.

Spec: docs/superpowers/specs/2026-06-23-coag-panel-physiology-design.md

After Tasks 2-4 add APTT / PT / Fibrinogen derives, the disease YAMLs that
already order these analytes (acute_mi, sepsis, gi_bleeding, subdural,
liver_cirrhosis_decompensated, etc.) must now produce RESULTED labs
instead of silently dropping.

Counterpart to test_panel_expansion_cbc_bmp.py — exercises the same
expansion / individual-order path for the Coag analyte family. The
post-hoc DR grouper itself is exhaustively unit-tested in
tests/unit/test_diagnostic_report_panels.py (TestGroupLabOrders,
TestBuildLabPanelReports, TestPanelYAMLs); this file confirms the
upstream CIF emission that the grouper consumes.
"""

import pytest

from clinosim.simulator import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig


@pytest.mark.integration
def test_acute_mi_emits_pt_inr_and_aptt():
    """acute_mi.yaml orders {test:"PT_INR"} and {test:"APTT"} at admission.
    After this PR's derive_lab_values extension both result with
    physiologic values (PT_INR existed pre-PR; APTT is new)."""
    scenario = ForcedScenario(
        disease_id="acute_mi", count=3, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    for record in dataset.patients:
        emitted = {
            o.result.lab_name
            for o in record.orders
            if o.result is not None and o.result.lab_name
        }
        assert {"PT_INR", "APTT"}.issubset(emitted), (
            f"acute_mi patient {record.patient.patient_id}: expected "
            f"both PT_INR and APTT in emitted labs, got {emitted & {'PT_INR', 'APTT'}}"
        )


@pytest.mark.integration
def test_sepsis_emits_pt_inr_and_fibrinogen():
    """sepsis.yaml orders both PT_INR (daily) and Fibrinogen (stat at admit).
    After this PR Fibrinogen results with a physiologic value (50-800 mg/dL,
    biphasic acute-phase / DIC behavior)."""
    scenario = ForcedScenario(
        disease_id="sepsis", count=3, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    for record in dataset.patients:
        fib_results = [
            o.result.value
            for o in record.orders
            if o.result is not None and o.result.lab_name == "Fibrinogen"
        ]
        pt_inr_results = [
            o.result.value
            for o in record.orders
            if o.result is not None and o.result.lab_name == "PT_INR"
        ]
        assert fib_results, (
            f"sepsis patient {record.patient.patient_id}: expected "
            f"at least one Fibrinogen result, got none"
        )
        assert pt_inr_results, (
            f"sepsis patient {record.patient.patient_id}: expected "
            f"at least one PT_INR result, got none"
        )
        for v in fib_results:
            assert 50 <= v <= 800, f"Fibrinogen {v} out of clamp range"
        for v in pt_inr_results:
            assert v > 0, f"PT_INR {v} must be positive"


@pytest.mark.integration
def test_pe_emits_clinically_positive_d_dimer():
    """End-to-end: pulmonary_embolism patients emit D-dimer Observations
    with median > 4 ug/mL FEU (clinically positive). Phase 2a."""
    scenario = ForcedScenario(
        disease_id="pulmonary_embolism", count=5, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    values = []
    for record in dataset.patients:
        for o in record.orders:
            if o.result is not None and o.result.lab_name == "D_dimer":
                values.append(o.result.value)
    assert values, "expected ≥1 D_dimer result across PE cohort"
    median = sorted(values)[len(values) // 2]
    assert median > 4.0, \
        f"PE D-dimer median {median} should be clinically positive (>4)"


@pytest.mark.integration
def test_ed_mi_now_emits_high_troponin_after_j5_fix():
    """J5 fix evidence: ED-route MI patients now produce MI-grade
    troponin (>5 ng/mL) instead of the pre-fix type-2 background
    (~0.5 ng/mL). Before the fix, emergency.py:122 called
    derive_lab_values without myocardial_injury=True so MI never
    upshifted troponin in the ED."""
    scenario = ForcedScenario(
        disease_id="acute_mi", count=5, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    troponins = []
    for record in dataset.patients:
        for o in record.orders:
            if o.result is not None and o.result.lab_name == "Troponin_I":
                troponins.append(o.result.value)
    assert troponins, "expected ≥1 Troponin_I result"
    high = [v for v in troponins if v > 5.0]
    assert high, (
        f"expected at least one MI-grade troponin (>5 ng/mL) in acute_mi "
        f"cohort after J5 fix; got values {sorted(troponins)[-5:]}"
    )


@pytest.mark.integration
def test_gi_bleeding_emits_pt_inr_and_aptt():
    """gi_bleeding.yaml orders both PT_INR and APTT at admission — DIC
    coagulopathy + hepatic synthesis defect scenarios make this protocol's
    coag panel diagnostically important."""
    scenario = ForcedScenario(
        disease_id="gi_bleeding", count=2, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    for record in dataset.patients:
        emitted = {
            o.result.lab_name
            for o in record.orders
            if o.result is not None and o.result.lab_name
        }
        assert {"PT_INR", "APTT"}.issubset(emitted), (
            f"gi_bleeding patient {record.patient.patient_id}: expected "
            f"both PT_INR and APTT in emitted labs, got "
            f"{emitted & {'PT_INR', 'APTT'}}"
        )
