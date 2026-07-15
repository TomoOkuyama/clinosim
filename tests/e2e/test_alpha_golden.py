"""End-to-end golden file test for run_alpha (backward compatibility).

Verifies that seed=42 produces identical structural data across runs.
Golden values updated when simulator behavior changes intentionally.
"""

from datetime import datetime

import pytest

from clinosim.simulator import run_alpha
from clinosim.types.config import SimulatorConfig

_SENTINEL_DATETIME = datetime(1970, 1, 1)

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
        # Inflammation should be lower at discharge than peak
        assert states[-1].inflammation_level < max(s.inflammation_level for s in states)
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

    def test_discharge_prescription_issue_date_is_deterministic(self, alpha_result):
        record = alpha_result.patients[0]
        assert record.discharge_prescription is not None
        assert record.discharge_prescription.issue_date != _SENTINEL_DATETIME
        result2 = run_alpha(SimulatorConfig(random_seed=42))
        assert result2.patients[0].discharge_prescription.issue_date == record.discharge_prescription.issue_date

    def test_state_and_prescription_timestamps_reproducible_across_runs(self, alpha_result):
        """Two independent run_alpha(seed=42) calls, with real wall-clock time
        elapsed between them, must produce byte-identical
        physiological_states[].timestamp and discharge_prescription.issue_date.
        This is the end-to-end proof that the determinism chain (2026-07-04)
        closed both byte-diff-measured live fields — if either still read
        datetime.now() under the hood, this test would be flaky (values would
        differ by however many milliseconds/seconds elapsed between the two
        calls below)."""
        result2 = run_alpha(SimulatorConfig(random_seed=42))
        r1 = alpha_result.patients[0]
        r2 = result2.patients[0]

        assert [s.timestamp for s in r1.physiological_states] == [s.timestamp for s in r2.physiological_states]

        assert r1.discharge_prescription is not None
        assert r2.discharge_prescription is not None
        assert r1.discharge_prescription.issue_date == r2.discharge_prescription.issue_date

    def test_cif_output(self, alpha_result, tmp_path):
        import json

        from clinosim.modules.output.cif_writer import write_cif

        output_dir = str(tmp_path / "cif")
        write_cif(alpha_result, output_dir)
        with open(f"{output_dir}/metadata.json") as f:
            metadata = json.load(f)
        assert metadata["random_seed"] == 42
