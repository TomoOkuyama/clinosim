"""End-to-end tests for US mode data generation.

Verifies that country="US" produces US-appropriate data:
  - English patient names
  - US-range LOS (shorter than JP)
  - LOINC lab codes in FHIR output
  - Home medications for chronic conditions
"""

import json

import pytest

from clinosim.simulator import run_beta, run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig


@pytest.fixture(scope="module")
def us_dataset():
    config = SimulatorConfig(
        catchment_population=5_000,
        random_seed=42,
        country="US",
    )
    return run_beta(config)


@pytest.mark.e2e
class TestUSMode:
    def test_generates_patients(self, us_dataset):
        assert len(us_dataset.patients) > 0
        assert us_dataset.metadata.country == "US"

    def test_english_names(self, us_dataset):
        for r in us_dataset.patients[:10]:
            name = r.patient.name
            assert name.name_script == "en"
            # No kanji/kana characters in family name
            assert all(ord(c) < 0x3000 for c in name.family_name), \
                f"Expected English name, got: {name.family_name}"

    def test_us_los_shorter_than_jp(self, us_dataset):
        """US pneumonia LOS should be significantly shorter than JP (14 days)."""
        pneumonia_patients = [
            r for r in us_dataset.patients
            if r.condition_event.ground_truth_diseases
            and r.condition_event.ground_truth_diseases[0] == "bacterial_pneumonia"
        ]
        if pneumonia_patients:
            avg_los = sum(len(r.physiological_states) - 1 for r in pneumonia_patients) / len(pneumonia_patients)
            assert avg_los < 10, f"US pneumonia avg LOS should be <10, got {avg_los:.1f}"

    def test_chronic_conditions_have_names(self, us_dataset):
        """All chronic conditions should resolve to proper English names via codes module."""
        from clinosim.codes import lookup
        for r in us_dataset.patients:
            for c in r.patient.chronic_conditions:
                display = lookup(c.system or "icd-10-cm", c.code, "en")
                assert display != c.code, f"Chronic condition display is just the code: {c.code}"

    def test_home_medications_present(self, us_dataset):
        """Inpatients with chronic conditions should have home medication orders."""
        inpatients_with_chronic = [
            r for r in us_dataset.patients
            if r.patient.chronic_conditions
            and r.encounters
            and r.encounters[0].encounter_type.value == "inpatient"
        ]
        patients_with_home_meds = [
            r for r in inpatients_with_chronic
            if any("Home medication" in o.clinical_intent for o in r.orders)
        ]
        if inpatients_with_chronic:
            ratio = len(patients_with_home_meds) / len(inpatients_with_chronic)
            assert ratio > 0.5, f"Expected >50% of chronic inpatients to have home meds, got {ratio:.0%}"

    def test_fhir_output_uses_loinc(self, us_dataset, tmp_path):
        from clinosim.modules.output.cif_writer import write_cif
        from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir

        cif_dir = str(tmp_path / "cif")
        fhir_dir = str(tmp_path / "fhir")
        write_cif(us_dataset, cif_dir)
        convert_cif_to_fhir(cif_dir, fhir_dir, country="US")

        # Bulk Data Export: Observation.ndjson contains lab Observations
        import os
        obs_path = os.path.join(fhir_dir, "Observation.ndjson")
        assert os.path.exists(obs_path)
        with open(obs_path) as f:
            for line in f:
                obs = json.loads(line)
                cats = obs.get("category", [])
                is_lab = any(
                    cat.get("coding", [{}])[0].get("code") == "laboratory"
                    for cat in cats
                )
                if is_lab:
                    code_system = obs["code"]["coding"][0].get("system", "")
                    assert "loinc" in code_system.lower(), f"Expected LOINC system, got: {code_system}"
                    return


@pytest.mark.e2e
class TestUSForcedScenario:
    def test_forced_us_pneumonia(self):
        scenario = ForcedScenario(
            disease_id="bacterial_pneumonia", count=3,
            severity="moderate",
        )
        config = SimulatorConfig(random_seed=42, country="US")
        dataset = run_forced(scenario, config)
        assert len(dataset.patients) == 3
        for r in dataset.patients:
            los = len(r.physiological_states) - 1
            assert los <= 10, f"US moderate pneumonia LOS should be <=10, got {los}"
