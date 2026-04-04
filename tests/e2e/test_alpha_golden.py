"""End-to-end golden file test for run_alpha (backward compatibility).

Verifies that seed=42 produces identical structural data across runs.
Golden values updated when simulator behavior changes intentionally.
"""

import pytest

from clinosim.simulator_beta import run_alpha
from clinosim.types.config import SimulatorConfig

GOLDEN = {
    "patient_id": "FORCED-0001",
    "age": 72,
    "sex": "F",
    "encounter_type": "inpatient",
    "los_days": 16,
    "lab_result_count": 57,
    "vital_sign_count": 47,
    "order_count": 63,
    "state_snapshot_count": 17,
    "initial_inflammation": 0.530,
    "peak_inflammation": 0.610,
    "final_inflammation": 0.000,
    "initial_renal": 0.668,
    "final_renal": 0.795,
}


@pytest.fixture(scope="module")
def alpha_result():
    return run_alpha(SimulatorConfig(random_seed=42))


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

    def test_clinical_plausibility(self, alpha_result):
        record = alpha_result.patients[0]
        states = record.physiological_states
        # Inflammation should peak in first few days, then decline
        peak_day = max(range(len(states)), key=lambda i: states[i].inflammation_level)
        assert peak_day <= 3
        # Renal function should improve
        assert states[-1].renal_function > states[0].renal_function
        # No state variable out of bounds
        for s in states:
            assert 0 <= s.inflammation_level <= 1
            assert 0 <= s.renal_function <= 1
            assert -1 <= s.volume_status <= 1
        # No negative lab values
        for r in record.lab_results:
            if r.value is not None and isinstance(r.value, (int, float)):
                assert r.value >= 0

    def test_reproducibility(self, alpha_result):
        result2 = run_alpha(SimulatorConfig(random_seed=42))
        r1 = alpha_result.patients[0]
        r2 = result2.patients[0]
        assert len(r1.lab_results) == len(r2.lab_results)

    def test_cif_output(self, alpha_result, tmp_path):
        from clinosim.modules.output.cif_writer import write_cif
        import json
        output_dir = str(tmp_path / "cif")
        write_cif(alpha_result, output_dir)
        with open(f"{output_dir}/metadata.json") as f:
            metadata = json.load(f)
        assert metadata["random_seed"] == 42
