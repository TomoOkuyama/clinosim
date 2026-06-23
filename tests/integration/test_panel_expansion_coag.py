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
