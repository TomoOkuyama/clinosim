"""End-to-end golden file test for v0.1-alpha.

Verifies that seed=42 produces identical structural data across runs.
If this test fails after a code change, either:
  - The change is a regression → fix the code
  - The change is intentional → update the golden values below with explanation
"""

import pytest

from clinosim.simulator import run_alpha
from clinosim.types.config import SimulatorConfig

# Golden values for seed=42 (generated 2026-04-04)
GOLDEN = {
    "patient_id": "P-ALPHA-001",
    "age": 72,
    "sex": "F",
    "encounter_type": "inpatient",
    "los_days": 15,
    "lab_result_count": 50,
    "vital_sign_count": 43,
    "order_count": 55,
    "state_snapshot_count": 16,
    "initial_inflammation": 0.530,
    "peak_inflammation": 0.580,
    "final_inflammation": 0.000,
    "initial_renal": 0.650,
    "final_renal": 0.780,
}


@pytest.fixture(scope="module")
def alpha_result():
    """Run alpha simulation once for all tests in this module."""
    config = SimulatorConfig(random_seed=42)
    return run_alpha(config)


@pytest.mark.e2e
class TestAlphaGolden:

    def test_patient_identity(self, alpha_result):
        record = alpha_result.patients[0]
        assert record.patient.patient_id == GOLDEN["patient_id"]
        assert record.patient.age == GOLDEN["age"]
        assert record.patient.sex == GOLDEN["sex"]

    def test_encounter_structure(self, alpha_result):
        enc = alpha_result.patients[0].encounters[0]
        assert enc.encounter_type.value == GOLDEN["encounter_type"]
        los = (enc.discharge_datetime - enc.admission_datetime).days
        assert los == GOLDEN["los_days"]

    def test_data_volume(self, alpha_result):
        record = alpha_result.patients[0]
        assert len(record.lab_results) == GOLDEN["lab_result_count"]
        assert len(record.vital_signs) == GOLDEN["vital_sign_count"]
        assert len(record.orders) == GOLDEN["order_count"]
        assert len(record.physiological_states) == GOLDEN["state_snapshot_count"]

    def test_inflammation_trajectory(self, alpha_result):
        states = alpha_result.patients[0].physiological_states
        initial = round(states[0].inflammation_level, 3)
        peak = round(max(s.inflammation_level for s in states), 3)
        final = round(states[-1].inflammation_level, 3)

        assert initial == GOLDEN["initial_inflammation"]
        assert peak == GOLDEN["peak_inflammation"]
        assert final == GOLDEN["final_inflammation"]

    def test_renal_trajectory(self, alpha_result):
        states = alpha_result.patients[0].physiological_states
        assert round(states[0].renal_function, 3) == GOLDEN["initial_renal"]
        assert round(states[-1].renal_function, 3) == GOLDEN["final_renal"]

    def test_reproducibility(self, alpha_result):
        """Same seed must produce identical results."""
        config = SimulatorConfig(random_seed=42)
        result2 = run_alpha(config)
        record1 = alpha_result.patients[0]
        record2 = result2.patients[0]

        # Structural data must be identical
        assert len(record1.lab_results) == len(record2.lab_results)
        assert len(record1.vital_signs) == len(record2.vital_signs)

        # State trajectories must be identical
        for s1, s2 in zip(record1.physiological_states, record2.physiological_states):
            assert s1.inflammation_level == s2.inflammation_level
            assert s1.renal_function == s2.renal_function

    def test_clinical_plausibility(self, alpha_result):
        """Basic clinical sanity checks."""
        record = alpha_result.patients[0]

        # Inflammation should peak in first 2 days, then decline
        states = record.physiological_states
        peak_day = max(range(len(states)), key=lambda i: states[i].inflammation_level)
        assert peak_day <= 2, f"Inflammation peaked on Day {peak_day}, expected Day 0-2"

        # Renal function should improve (rehydration)
        assert states[-1].renal_function > states[0].renal_function

        # No state variable out of bounds
        for s in states:
            assert 0 <= s.inflammation_level <= 1
            assert 0 <= s.renal_function <= 1
            assert 0 <= s.perfusion_status <= 1
            assert -1 <= s.volume_status <= 1

        # Lab results: no negative values
        for r in record.lab_results:
            if r.value is not None and isinstance(r.value, (int, float)):
                assert r.value >= 0, f"Negative lab value: {r.value}"

    def test_cif_output(self, alpha_result, tmp_path):
        """CIF writer produces valid JSON files."""
        from clinosim.modules.output.cif_writer import write_cif
        import json

        output_dir = str(tmp_path / "cif")
        write_cif(alpha_result, output_dir)

        # Metadata exists and is valid JSON
        with open(f"{output_dir}/metadata.json") as f:
            metadata = json.load(f)
        assert metadata["clinosim_version"] == "0.1.0-alpha"
        assert metadata["random_seed"] == 42

        # Patient file exists and is valid JSON
        with open(f"{output_dir}/structural/patients/P-ALPHA-001.json") as f:
            patient = json.load(f)
        assert patient["patient"]["patient_id"] == "P-ALPHA-001"
        assert len(patient["vital_signs"]) == GOLDEN["vital_sign_count"]
