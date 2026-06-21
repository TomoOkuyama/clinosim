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


def test_code_status_csv_written(tmp_path):
    cif, out = str(tmp_path / "cif"), str(tmp_path / "out")
    _write_cif(cif, {"patient": {"patient_id": "P1"},
                     "encounters": [{"encounter_id": "E1", "encounter_type": "inpatient"}],
                     "code_status": "304253006"})
    convert_cif_to_csv(cif, out, country="US")
    path = os.path.join(out, "code_status.csv")
    assert os.path.exists(path)
    rows = list(csv.DictReader(open(path)))
    assert rows[0]["patient_id"] == "P1" and rows[0]["code"] == "304253006"
    assert rows[0]["encounter_id"] == "E1"
