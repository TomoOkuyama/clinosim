import json
import subprocess
import sys
from pathlib import Path

import pytest


def _write_tiny_structural(tmp_path: Path):
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(json.dumps({
        "patient": {"patient_id": "POP-1", "age": 65, "sex": "M"},
        "encounters": [{"encounter_id": "ENC-1",
                        "encounter_type": {"value": "inpatient"}}],
        "documents": [{"document_id": "doc-1", "task_type": "admission_hp",
                       "loinc_code": "34117-2", "format_type": "composition",
                       "narrative": None}],
        "vitals": [], "lab_results": [], "medications": [], "diagnoses": [],
        "procedures": [], "allergies": [],
    }))


@pytest.mark.unit
def test_narrate_template_writes_dir_and_pointer(tmp_path):
    _write_tiny_structural(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "narrate",
         "--cif-dir", str(tmp_path), "--provider", "template",
         "--country", "US"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "narratives/template/documents/ENC-1").exists()
    pointer = (tmp_path / "narratives/current_version.txt").read_text().strip()
    assert pointer == "template"


@pytest.mark.unit
def test_narrate_no_set_current_leaves_pointer(tmp_path):
    _write_tiny_structural(tmp_path)
    (tmp_path / "narratives").mkdir(exist_ok=True)
    (tmp_path / "narratives" / "current_version.txt").write_text("prior")
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "narrate",
         "--cif-dir", str(tmp_path), "--provider", "template",
         "--country", "US", "--no-set-current"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    pointer = (tmp_path / "narratives/current_version.txt").read_text().strip()
    assert pointer == "prior"


@pytest.mark.unit
def test_narrate_tasks_filter(tmp_path):
    _write_tiny_structural(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "narrate",
         "--cif-dir", str(tmp_path), "--provider", "template",
         "--tasks", "progress_note", "--country", "US"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    # admission_hp should not appear
    assert not (tmp_path / "narratives/template/documents/ENC-1/admission_hp.json").exists()


@pytest.mark.unit
def test_narrate_bedrock_provider_raises_not_implemented(tmp_path):
    _write_tiny_structural(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "narrate",
         "--cif-dir", str(tmp_path), "--provider", "bedrock",
         "--country", "US"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    # β-JP-1 defer message
    assert "β-JP-1" in r.stderr or "beta-jp-1" in r.stderr.lower() or \
           "NotImplementedError" in r.stderr
