"""CSV adapter microbiology.csv code/system columns (TODO.md 2026-07-04 follow-up).

Renamed from test_loinc/antibiotic_loinc (columns named after a fixed code
system) to test_code/test_code_system + antibiotic_code/antibiotic_code_system
(a code/system pair, like FHIR), resolved via the same
resolve_culture_code/resolve_susceptibility_code single source of truth the
FHIR builder uses — so CSV and FHIR output stay consistent for JP.
"""

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


def _base_record(microbiology: list[dict]) -> dict:
    return {
        "patient": {"patient_id": "P1"},
        "encounters": [{"encounter_id": "E1", "encounter_type": "inpatient"}],
        "microbiology": microbiology,
    }


def test_jp_culture_and_susceptibility_use_jlac10_columns(tmp_path):
    cif = str(tmp_path / "cif")
    out = str(tmp_path / "out")
    _write_cif(
        cif,
        _base_record(
            [
                {
                    "encounter_id": "E1",
                    "specimen": "blood",
                    "specimen_snomed": "119297000",
                    "test_loinc": "600-7",
                    "growth": True,
                    "organism_snomed": "3092008",
                    "quantitation": "",
                    "susceptibilities": [{"antibiotic_loinc": "18862-3", "interpretation": "S"}],
                    "hai_event_id": "",
                }
            ]
        ),
    )
    convert_cif_to_csv(cif, out, country="JP")
    path = os.path.join(out, "microbiology.csv")
    assert os.path.exists(path)
    rows = list(csv.DictReader(open(path)))
    assert len(rows) == 1
    row = rows[0]
    assert row["test_code"] == "6B010"
    assert row["test_code_system"] == "jlac10"
    assert row["antibiotic_code"] == "6C010"
    assert row["antibiotic_code_system"] == "jlac10"
    assert "test_loinc" not in row
    assert "antibiotic_loinc" not in row


def test_us_culture_and_susceptibility_use_loinc_columns(tmp_path):
    cif = str(tmp_path / "cif")
    out = str(tmp_path / "out")
    _write_cif(
        cif,
        _base_record(
            [
                {
                    "encounter_id": "E1",
                    "specimen": "blood",
                    "specimen_snomed": "119297000",
                    "test_loinc": "600-7",
                    "growth": True,
                    "organism_snomed": "3092008",
                    "quantitation": "",
                    "susceptibilities": [{"antibiotic_loinc": "18862-3", "interpretation": "S"}],
                    "hai_event_id": "",
                }
            ]
        ),
    )
    convert_cif_to_csv(cif, out, country="US")
    path = os.path.join(out, "microbiology.csv")
    rows = list(csv.DictReader(open(path)))
    row = rows[0]
    assert row["test_code"] == "600-7"
    assert row["test_code_system"] == "loinc"
    assert row["antibiotic_code"] == "18862-3"
    assert row["antibiotic_code_system"] == "loinc"


def test_jp_no_growth_culture_has_no_susceptibility_row_but_correct_test_code(tmp_path):
    cif = str(tmp_path / "cif")
    out = str(tmp_path / "out")
    _write_cif(
        cif,
        _base_record(
            [
                {
                    "encounter_id": "E1",
                    "specimen": "urine",
                    "specimen_snomed": "122575003",
                    "test_loinc": "630-4",
                    "growth": False,
                    "organism_snomed": "",
                    "quantitation": "",
                    "susceptibilities": [],
                    "hai_event_id": "",
                }
            ]
        ),
    )
    convert_cif_to_csv(cif, out, country="JP")
    path = os.path.join(out, "microbiology.csv")
    rows = list(csv.DictReader(open(path)))
    assert len(rows) == 1
    row = rows[0]
    assert row["test_code"] == "6B010"
    assert row["test_code_system"] == "jlac10"
    assert row["antibiotic_code"] == ""
    assert row["antibiotic_code_system"] == ""
