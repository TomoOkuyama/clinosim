"""E2E tests for ForcedScenario and mixed condition simulation."""

import pytest

from clinosim.simulator import run_beta, run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig


@pytest.mark.e2e
class TestForcedScenario:
    def test_generates_specified_count(self):
        scenario = ForcedScenario(disease_id="bacterial_pneumonia", count=5)
        dataset = run_forced(scenario)
        assert len(dataset.patients) == 5

    def test_forces_archetype(self):
        scenario = ForcedScenario(
            disease_id="bacterial_pneumonia", count=5,
            severity="moderate", archetype="treatment_resistant",
        )
        dataset = run_forced(scenario)
        # At least some patients should have treatment modification orders
        patients_with_mods = sum(
            1 for r in dataset.patients
            if any("STOP" in o.order_id or "START" in o.order_id for o in r.orders)
        )
        assert patients_with_mods > 0, "treatment_resistant should have drug changes in some patients"

    def test_forces_severity(self):
        scenario = ForcedScenario(
            disease_id="bacterial_pneumonia", count=3, severity="severe",
        )
        dataset = run_forced(scenario)
        for r in dataset.patients:
            # Severe patients should have higher initial inflammation
            assert r.physiological_states[0].inflammation_level > 0.6

    def test_patient_overrides(self):
        scenario = ForcedScenario(
            disease_id="bacterial_pneumonia", count=2,
            patient_overrides={"age": 25, "sex": "M"},
        )
        dataset = run_forced(scenario)
        for r in dataset.patients:
            assert r.patient.age == 25
            assert r.patient.sex == "M"

    def test_hip_fracture_has_surgery(self):
        scenario = ForcedScenario(disease_id="hip_fracture", count=2)
        dataset = run_forced(scenario)
        for r in dataset.patients:
            assert len(r.procedures) > 0, "hip fracture should have surgery"
            assert len(r.rehab_sessions) > 0, "hip fracture should have rehab"


@pytest.fixture(scope="module")
def mixed_dataset():
    config = SimulatorConfig(
        catchment_population=30_000, random_seed=42,
        time_range=("2024-04-01", "2025-03-31"),
    )
    return run_beta(config)


@pytest.mark.e2e
class TestMixedCondition:
    def test_mixed_patients_exist(self, mixed_dataset):
        mixed = [r for r in mixed_dataset.patients if r.condition_event.condition_type == "mixed"]
        assert len(mixed) > 0, "Should have some mixed condition patients"

    def test_mixed_has_dual_ground_truth(self, mixed_dataset):
        mixed = [r for r in mixed_dataset.patients if r.condition_event.condition_type == "mixed"]
        if mixed:
            r = mixed[0]
            assert len(r.condition_event.ground_truth_diseases) >= 2

    def test_mixed_state_reflects_both_diseases(self, mixed_dataset):
        mixed = [r for r in mixed_dataset.patients if r.condition_event.condition_type == "mixed"]
        if mixed:
            r = mixed[0]
            s = r.physiological_states[0]
            assert s.inflammation_level > 0.3, "Should have inflammation from pneumonia"
