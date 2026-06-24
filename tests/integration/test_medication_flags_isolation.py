"""Integration test: medication_flags_from_context preserves AD-16 determinism.

Mirrors test_individual_lab_isolation.py: two seeded runs of the same
ForcedScenario must produce byte-identical PT_INR distributions —
confirming the medication-flag detection path is deterministic and
does NOT draw from the patient-scoped master RNG.

This regression-guards future couplings: when Phase 2c adds another
medication flag (e.g., on_therapeutic_heparin), the same determinism
property must hold.
"""
from __future__ import annotations

import pytest

from clinosim.simulator import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig


def _collect_pt_inr_values(dataset):
    """Sorted PT_INR values across all patients in the dataset."""
    vals: list[float] = []
    for record in dataset.patients:
        for r in record.lab_results:
            if r.lab_name == "PT_INR" and isinstance(r.value, (int, float)):
                vals.append(float(r.value))
    return sorted(vals)


@pytest.mark.integration
def test_pt_inr_distribution_deterministic_under_same_seed():
    """Same ForcedScenario + same seed → byte-identical PT_INR distribution.

    Property: medication_flags_from_context is a pure peek (no RNG draw),
    so wiring it into the lab loop must not change determinism. If two
    runs disagree, the helper or its call-site merge is leaking
    nondeterminism into the lab generation path.
    """
    scenario = ForcedScenario(disease_id="urinary_tract_infection", count=5,
                              severity="moderate")
    cfg = SimulatorConfig(random_seed=42, country="US")

    run1 = run_forced(scenario, cfg)
    run2 = run_forced(scenario, cfg)

    pt_inrs_1 = _collect_pt_inr_values(run1)
    pt_inrs_2 = _collect_pt_inr_values(run2)

    assert pt_inrs_1 == pt_inrs_2, \
        "PT_INR distribution must be deterministic under same seed (AD-16)"


@pytest.mark.integration
def test_pt_inr_distribution_deterministic_pe_cohort():
    """Same property for PE cohort (where in-hospital warfarin ramp path
    is exercised — chronic_medications I26 entry + day-3 gate)."""
    scenario = ForcedScenario(disease_id="pulmonary_embolism", count=5,
                              severity="moderate")
    cfg = SimulatorConfig(random_seed=42, country="US")

    run1 = run_forced(scenario, cfg)
    run2 = run_forced(scenario, cfg)

    pt_inrs_1 = _collect_pt_inr_values(run1)
    pt_inrs_2 = _collect_pt_inr_values(run2)

    assert pt_inrs_1 == pt_inrs_2, \
        "PE cohort PT_INR distribution must be deterministic under same seed"
