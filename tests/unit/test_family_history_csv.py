import csv
import json
import os

import pytest

from clinosim.modules.output.csv_adapter import convert_cif_to_csv

pytestmark = pytest.mark.unit


def _write_cif(cif_dir: str, record: dict) -> None:
    pdir = os.path.join(cif_dir, "structural", "patients")
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, "P1.json"), "w") as f:
        json.dump(record, f)


def test_family_history_csv_written(tmp_path):
    cif = str(tmp_path / "cif")
    out = str(tmp_path / "out")
    _write_cif(
        cif,
        {
            "patient": {"patient_id": "P1"},
            "encounters": [{"encounter_id": "E1", "encounter_type": "outpatient"}],
            "family_history": [
                {"relationship": "MTH", "sex": "female", "deceased": True, "condition_codes": ["E11", "C50"]},
            ],
        },
    )
    convert_cif_to_csv(cif, out, country="US")
    path = os.path.join(out, "family_history.csv")
    assert os.path.exists(path)
    rows = list(csv.DictReader(open(path)))
    assert {"E11", "C50"} == {r["condition_code"] for r in rows}
    assert rows[0]["relationship"] == "MTH" and rows[0]["patient_id"] == "P1"
