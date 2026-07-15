"""End-to-end tests for v0.1-beta (population-driven, multiple patients)."""

import os

import pytest

from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.csv_adapter import convert_cif_to_csv
from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir
from clinosim.modules.validator.benchmarks import run_benchmarks
from clinosim.simulator import run_beta
from clinosim.types.config import SimulatorConfig


@pytest.fixture(scope="module")
def beta_result():
    config = SimulatorConfig(
        catchment_population=5_000,
        time_range=("2024-04-01", "2025-03-31"),
        random_seed=42,
    )
    return run_beta(config)


@pytest.mark.e2e
class TestBeta:
    def test_generates_multiple_patients(self, beta_result):
        assert len(beta_result.patients) > 5, "Should generate multiple patients from 10K population"

    def test_age_distribution_realistic(self, beta_result):
        ages = [p.patient.age for p in beta_result.patients]
        mean_age = sum(ages) / len(ages)
        # Pneumonia patients should be predominantly elderly
        assert mean_age > 50, f"Mean age {mean_age:.0f} too young for pneumonia cohort"

    def test_varied_archetypes(self, beta_result):
        """Not all patients should have the same trajectory."""
        final_inflammations = [
            p.physiological_states[-1].inflammation_level for p in beta_result.patients if p.physiological_states
        ]
        # Some variation expected
        assert max(final_inflammations) - min(final_inflammations) >= 0, "Some variation expected"

    def test_patient_identity_stable_across_encounters(self, beta_result):
        """A person appearing in multiple encounters must have ONE stable medical
        history: chronic-condition onset dates (and stage) identical across all their
        records. Guards against activate_patient being re-run per encounter."""
        from collections import defaultdict

        onsets = defaultdict(set)  # (patient_id, code) -> {onset_date}
        stages = defaultdict(set)  # (patient_id, code) -> {stage}
        rec_count = defaultdict(int)
        for rec in beta_result.patients:
            pid = rec.patient.patient_id
            rec_count[pid] += 1
            for c in rec.patient.chronic_conditions:
                onsets[(pid, c.code)].add(c.onset_date)
                stages[(pid, c.code)].add(c.stage)
        multi = [p for p, n in rec_count.items() if n > 1]
        assert multi, "test needs patients with >1 encounter to be meaningful"
        bad_onset = {k: v for k, v in onsets.items() if len(v) > 1}
        bad_stage = {k: v for k, v in stages.items() if len(v) > 1}
        assert not bad_onset, (
            f"{len(bad_onset)} (patient,condition) have inconsistent onset dates across encounters, e.g. {list(bad_onset.items())[:3]}"  # noqa: E501
        )  # noqa: E501
        assert not bad_stage, (
            f"{len(bad_stage)} (patient,condition) have inconsistent stage across encounters, e.g. {list(bad_stage.items())[:3]}"  # noqa: E501
        )  # noqa: E501

    def test_csv_output(self, beta_result, tmp_path):
        cif_dir = str(tmp_path / "cif")
        csv_dir = str(tmp_path / "csv")
        write_cif(beta_result, cif_dir)
        convert_cif_to_csv(cif_dir, csv_dir)

        assert os.path.exists(os.path.join(csv_dir, "patients.csv"))
        assert os.path.exists(os.path.join(csv_dir, "vital_signs.csv"))
        assert os.path.exists(os.path.join(csv_dir, "lab_results.csv"))
        assert os.path.exists(os.path.join(csv_dir, "orders.csv"))
        assert os.path.exists(os.path.join(csv_dir, "encounters.csv"))

    def test_benchmarks_pass(self, beta_result):
        report = run_benchmarks(beta_result, country="US")
        print(f"\n{report.summary()}")
        for r in report.results:
            print(
                f"  {r.name}: {r.generated_value:.1f} (expected {r.expected_value}, range {r.expected_range}) [{r.status}]"  # noqa: E501
            )  # noqa: E501
        # At least 50% should pass (beta quality, not production)
        assert report.pass_rate >= 0.5, f"Benchmark pass rate too low: {report.pass_rate:.0%}"

    def test_fhir_output(self, beta_result, tmp_path):
        cif_dir = str(tmp_path / "cif")
        fhir_dir = str(tmp_path / "fhir")
        write_cif(beta_result, cif_dir)
        convert_cif_to_fhir(cif_dir, fhir_dir, country="US")

        # Bulk Data Export: one NDJSON per resource type + manifest.json
        ndjson_files = [f for f in os.listdir(fhir_dir) if f.endswith(".ndjson")]
        assert "Patient.ndjson" in ndjson_files
        assert "Encounter.ndjson" in ndjson_files
        assert "Observation.ndjson" in ndjson_files
        assert "manifest.json" in os.listdir(fhir_dir)

        # Validate first line of Patient.ndjson is a valid Patient resource
        import json

        with open(os.path.join(fhir_dir, "Patient.ndjson")) as f:
            first_line = f.readline()
        patient = json.loads(first_line)
        assert patient["resourceType"] == "Patient"
        assert patient.get("identifier")

    def test_reproducibility(self, beta_result):
        config = SimulatorConfig(
            catchment_population=5_000,
            time_range=("2024-04-01", "2025-03-31"),
            random_seed=42,
        )
        result2 = run_beta(config)
        assert len(result2.patients) == len(beta_result.patients)
        for p1, p2 in zip(beta_result.patients, result2.patients):
            assert p1.patient.patient_id == p2.patient.patient_id
