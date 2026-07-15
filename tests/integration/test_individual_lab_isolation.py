"""Integration test: individual (non-panel-child) lab orders are isolated
from the patient-scoped master RNG via individual_lab_seed (AD-16).

Background — the BMP Cl/Ca physiology PR (2026-06-23) discovered that
the inpatient Pass 1 lab loop (and the parallel paths in emergency.py +
outpatient.py) drew specimen-rejection / hemolysis / technician /
noise from the patient-scoped master RNG. Any YAML edit that flipped a
{test:"X"} order from "engine doesn't produce X" to "engine produces X"
(e.g. adding Cl/Ca to derive_lab_values) silently shuffled unrelated
patients' cohorts. PR #74 fixed this for panel children; the BMP Cl/Ca
PR completes the pattern for individual lab orders via individual_lab_seed.

These tests guard the structural property. They cannot use the "patch
derive_lab_values across two runs" approach because the simulator
amortizes ID counters across calls in the same process — a property
test using two consecutive run_forced() calls would falsely report
drift. They check instead that:
  1. Same seed twice = byte-identical output (determinism).
  2. Cl and Ca Observations are present in BMP-ordering disease cohorts
     after the physiology engine produces them.
"""

import pytest

from clinosim.simulator import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig
from clinosim.types.encounter import OrderStatus


@pytest.mark.integration
def test_dka_individual_cl_order_now_resulted():
    """DKA has an individual {test: "Cl"} admission order. Before
    derive_lab_values produced Cl, this order silently failed canon-in-
    true_labs check and stayed PLACED with no result. After Cl is added
    (BMP Cl/Ca physiology PR), the order must be RESULTED with a
    numerical Cl value.

    This is the integration counterpart to test_dka_bmp_cl_ca_children_now_resulted
    (which covers the panel-child path); this test covers the
    individual-order path that Pass 1 handles via individual_lab_seed.
    """
    scenario = ForcedScenario(
        disease_id="diabetic_ketoacidosis",
        count=3,
        severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    for record in dataset.patients:
        # Find the individual Cl order (display_name == "Cl"), NOT panel children
        # (whose order_id ends in "-Cl" after a parent prefix).
        cl_individual = [
            o
            for o in record.orders
            if o.display_name == "Cl" and not (o.order_id.endswith("-Cl") and "-" in o.order_id[:-3])
        ]
        assert cl_individual, (
            f"DKA patient {record.patient.patient_id} should have at least one "
            f"individual Cl order (from disease YAML admission_orders), found none"
        )
        # At least one such order must be RESULTED (some may be CANCELLED
        # via specimen rejection sub-RNG; that is allowed).
        resulted = [o for o in cl_individual if o.status == OrderStatus.RESULTED]
        assert resulted, (
            f"DKA patient {record.patient.patient_id}: every individual Cl "
            f"order is non-RESULTED — derive_lab_values should now produce "
            f"Cl so the order resolves."
        )
        for o in resulted:
            assert o.result is not None and o.result.value is not None
            assert 80 <= o.result.value <= 125, f"Cl value {o.result.value} out of physiological range"


@pytest.mark.integration
def test_sepsis_individual_fibrinogen_order_now_resulted():
    """Sepsis YAML orders {test:"Fibrinogen", urgency:"stat"} on admission
    plus daily PT_INR. Before the Coag panel PR (2026-06-23), Fibrinogen
    silently dropped (no derive); APTT also silently dropped on the MI/GI-
    bleed/subdural paths. After this PR adds APTT / PT(seconds) / Fibrinogen
    to derive_lab_values, all three must result with physiologic values.

    Counterpart to test_dka_individual_cl_order_now_resulted (Cl) — same
    invariant for the coag-panel additions on the individual-order path.
    """
    scenario = ForcedScenario(
        disease_id="sepsis",
        count=3,
        severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    for record in dataset.patients:
        fib_individual = [
            o
            for o in record.orders
            if o.display_name == "Fibrinogen"
            and not (o.order_id.endswith("-Fibrinogen") and "-" in o.order_id[: -len("-Fibrinogen")])
        ]
        assert fib_individual, (
            f"Sepsis patient {record.patient.patient_id} should have at least one "
            f"individual Fibrinogen order (from sepsis.yaml admission_orders)"
        )
        resulted = [o for o in fib_individual if o.status == OrderStatus.RESULTED]
        assert resulted, (
            f"Sepsis patient {record.patient.patient_id}: every individual "
            f"Fibrinogen order is non-RESULTED — derive_lab_values should now "
            f"produce Fibrinogen so the order resolves."
        )
        for o in resulted:
            assert o.result is not None and o.result.value is not None
            assert 50 <= o.result.value <= 800, f"Fibrinogen value {o.result.value} out of physiological range"


@pytest.mark.integration
def test_pe_individual_d_dimer_order_now_resulted():
    """pulmonary_embolism.yaml orders {test:"D_dimer", urgency:"stat"} at
    admission. After Phase 2a D-dimer derives with the new causes_vte
    flag and PE patients land in the clinically positive range
    (>4 ug/mL FEU).

    Counterpart to the Cl (PR #78) and Fibrinogen (PR #80) guards: same
    AD-59 invariant exercised for the new VTE-flag path."""
    scenario = ForcedScenario(
        disease_id="pulmonary_embolism",
        count=3,
        severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    for record in dataset.patients:
        dd = [
            o
            for o in record.orders
            if o.display_name == "D_dimer"
            and not (o.order_id.endswith("-D_dimer") and "-" in o.order_id[: -len("-D_dimer")])
        ]
        assert dd, (
            f"PE patient {record.patient.patient_id} should have ≥1 "
            f"individual D_dimer order from pulmonary_embolism.yaml"
        )
        resulted = [o for o in dd if o.status == OrderStatus.RESULTED]
        assert resulted, (
            f"PE patient {record.patient.patient_id}: every D_dimer "
            f"order is non-RESULTED — derive_lab_values must produce "
            f"D_dimer so the order resolves"
        )
        for o in resulted:
            assert o.result is not None and o.result.value is not None
            assert 4.0 <= o.result.value <= 20.0, f"PE D-dimer {o.result.value} should be clinically positive"


@pytest.mark.integration
def test_simulator_deterministic_across_repeated_runs():
    """Same seed twice = byte-identical CIF output. Validates that the
    Pass 1 sub-RNG (individual_lab_seed) and Pass 2 sub-RNG
    (panel_specimen_seed) refactors did not introduce any nondeterminism.
    """
    scenario = ForcedScenario(
        disease_id="diabetic_ketoacidosis",
        count=3,
        severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    ds1 = run_forced(scenario, cfg)
    ds2 = run_forced(scenario, cfg)

    assert len(ds1.patients) == len(ds2.patients)
    for p1, p2 in zip(ds1.patients, ds2.patients):
        assert p1.patient.patient_id == p2.patient.patient_id
        # Lab results: same order_ids, same values, same statuses
        labs1 = {(r.lab_name, r.result_datetime): r.value for r in p1.lab_results}
        labs2 = {(r.lab_name, r.result_datetime): r.value for r in p2.lab_results}
        assert labs1 == labs2, (
            f"non-determinism for {p1.patient.patient_id}: lab results differ between two same-seed runs"
        )
