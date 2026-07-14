"""Integration test for the full Layer 1→2→1→readmission cycle."""

import os

import pytest

from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.csv_adapter import convert_cif_to_csv
from clinosim.simulator import run_beta
from clinosim.types.config import SimulatorConfig


@pytest.fixture(scope="module")
def readmission_dataset():
    config = SimulatorConfig(
        catchment_population=5_000,
        random_seed=42,
        country="US",
    )
    return run_beta(config)


@pytest.mark.integration
class TestReadmissionFlow:
    def test_readmissions_exist(self, readmission_dataset):
        readmits = [r for r in readmission_dataset.patients if r.is_readmission]
        assert len(readmits) > 0, "Should have some readmissions"

    def test_readmission_has_prior_encounter(self, readmission_dataset):
        readmits = [r for r in readmission_dataset.patients if r.is_readmission]
        for r in readmits:
            assert r.prior_encounter_id is not None
            assert r.readmission_number >= 1

    def test_readmission_encounter_id_differs_from_prior(self, readmission_dataset):
        readmits = [r for r in readmission_dataset.patients if r.is_readmission]
        for r in readmits:
            enc_id = r.encounters[0].encounter_id if r.encounters else None
            assert enc_id != r.prior_encounter_id, \
                f"Readmission encounter {enc_id} should differ from prior {r.prior_encounter_id}"

    def test_same_patient_appears_twice(self, readmission_dataset):
        """A readmitted patient should have both initial and readmission records."""
        readmit_pids = {r.patient.patient_id for r in readmission_dataset.patients if r.is_readmission}
        first_pids = {r.patient.patient_id for r in readmission_dataset.patients if not r.is_readmission}
        overlap = readmit_pids & first_pids
        assert len(overlap) > 0, "Should have patients appearing in both initial and readmission"

    def test_no_surgical_readmissions(self, readmission_dataset):
        """Hip fracture should not have same-disease readmissions."""
        readmits = [r for r in readmission_dataset.patients if r.is_readmission]
        for r in readmits:
            diseases = r.condition_event.ground_truth_diseases
            assert "hip_fracture" not in diseases, "Surgical conditions should not readmit"

    def test_csv_diagnoses_table(self, readmission_dataset, tmp_path):
        cif_dir = str(tmp_path / "cif")
        csv_dir = str(tmp_path / "csv")
        write_cif(readmission_dataset, cif_dir)
        convert_cif_to_csv(cif_dir, csv_dir)

        assert os.path.exists(os.path.join(csv_dir, "diagnoses.csv"))

        import csv
        with open(os.path.join(csv_dir, "diagnoses.csv")) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) > 0
        assert "discharge_diagnosis_code" in rows[0]
        assert "ground_truth_diseases" in rows[0]

    def test_csv_diagnosis_names_are_resolved(self, readmission_dataset, tmp_path):
        # Regression (FA-4): CIF has no *_diagnosis_name field; the CSV adapter must
        # resolve the display from the stored code + system (AD-30). It used to read a
        # ghost field, leaving the name columns always empty.
        cif_dir = str(tmp_path / "cif")
        csv_dir = str(tmp_path / "csv")
        write_cif(readmission_dataset, cif_dir)
        convert_cif_to_csv(cif_dir, csv_dir, country="US")

        import csv
        with open(os.path.join(csv_dir, "diagnoses.csv")) as f:
            rows = list(csv.DictReader(f))
        coded = [r for r in rows if r["discharge_diagnosis_code"]]
        assert coded, "expected some rows with a discharge diagnosis code"
        for r in coded:
            assert r["discharge_diagnosis_name"], (
                f"diagnosis name must be resolved for code {r['discharge_diagnosis_code']}"
            )

    def test_readmission_rate_within_benchmark(self, readmission_dataset):
        """Overall readmission rate (inpatient only) should be between 5-40%."""
        inpatients = [
            r for r in readmission_dataset.patients
            if r.encounters and r.encounters[0].encounter_type.value == "inpatient"
        ]
        total_first = sum(1 for r in inpatients if not r.is_readmission)
        total_readmit = sum(1 for r in inpatients if r.is_readmission)
        if total_first > 0:
            rate = total_readmit / total_first
            assert 0.05 <= rate <= 0.40, f"Readmission rate {rate:.0%} outside expected range"
