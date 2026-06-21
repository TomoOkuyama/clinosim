import csv
import json
import os

import pytest

from clinosim.modules.output.csv_adapter import convert_cif_to_csv

pytestmark = pytest.mark.unit


def _write_cif(cif_dir, record):
    pdir = os.path.join(cif_dir, "structural", "patients")
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, "P1.json"), "w") as f:
        json.dump(record, f)


def test_alcohol_in_patients_csv_and_care_level_csv(tmp_path):
    cif, out = str(tmp_path / "cif"), str(tmp_path / "out")
    _write_cif(cif, {"patient": {"patient_id": "P1", "alcohol_use": "social"},
                     "encounters": [{"encounter_id": "E1", "encounter_type": "inpatient"}],
                     "care_level": "care2"})
    convert_cif_to_csv(cif, out, country="JP")
    prows = list(csv.DictReader(open(os.path.join(out, "patients.csv"))))
    assert prows[0]["alcohol_use"] == "social"
    crows = list(csv.DictReader(open(os.path.join(out, "care_level.csv"))))
    assert crows[0]["patient_id"] == "P1" and crows[0]["code"] == "care2"
