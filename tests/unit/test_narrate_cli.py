import json
import subprocess
import sys
from pathlib import Path

import pytest


def _write_tiny_structural(tmp_path: Path):
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(
        json.dumps(
            {
                "patient": {"patient_id": "POP-1", "age": 65, "sex": "M"},
                "encounters": [{"encounter_id": "ENC-1", "encounter_type": {"value": "inpatient"}}],
                "documents": [
                    {
                        "document_id": "doc-1",
                        "task_type": "admission_hp",
                        "loinc_code": "34117-2",
                        "format_type": "composition",
                        "narrative": None,
                    }
                ],
                "vitals": [],
                "lab_results": [],
                "medications": [],
                "diagnoses": [],
                "procedures": [],
                "allergies": [],
            }
        )
    )


@pytest.mark.unit
def test_narrate_template_writes_dir_and_pointer(tmp_path):
    _write_tiny_structural(tmp_path)
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "narrate",
            "--cif-dir",
            str(tmp_path),
            "--provider",
            "template",
            "--country",
            "US",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "narratives/template/documents/ENC-1").exists()
    pointer = (tmp_path / "narratives/current_version.txt").read_text().strip()
    assert pointer == "template"
    # M-3: pointer updates are always announced on stdout
    assert "current -> template" in r.stdout


@pytest.mark.unit
def test_narrate_no_set_current_leaves_pointer(tmp_path):
    _write_tiny_structural(tmp_path)
    (tmp_path / "narratives").mkdir(exist_ok=True)
    (tmp_path / "narratives" / "current_version.txt").write_text("prior")
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "narrate",
            "--cif-dir",
            str(tmp_path),
            "--provider",
            "template",
            "--country",
            "US",
            "--no-set-current",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    pointer = (tmp_path / "narratives/current_version.txt").read_text().strip()
    assert pointer == "prior"


@pytest.mark.unit
def test_narrate_tasks_filter(tmp_path):
    _write_tiny_structural(tmp_path)
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "narrate",
            "--cif-dir",
            str(tmp_path),
            "--provider",
            "template",
            "--tasks",
            "progress_note",
            "--country",
            "US",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    # admission_hp should not appear
    assert not (tmp_path / "narratives/template/documents/ENC-1/admission_hp.json").exists()


@pytest.mark.unit
def test_narrate_llm_provider_missing_config_fails_loud(tmp_path):
    """--llm-config pointing nowhere must fail loudly (no silent template run)."""
    _write_tiny_structural(tmp_path)
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "narrate",
            "--cif-dir",
            str(tmp_path),
            "--provider",
            "bedrock",
            "--llm-config",
            str(tmp_path / "does_not_exist.yaml"),
            "--country",
            "US",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "FileNotFoundError" in r.stderr or "not found" in r.stderr
    # Nothing was written under an LLM version dir
    assert not (tmp_path / "narratives" / "bedrock").exists()


@pytest.mark.unit
def test_narrate_mock_provider_writes_llm_version_dir(tmp_path):
    """--provider mock runs LLMNarrativePass end-to-end (no network)."""
    _write_tiny_structural(tmp_path)
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "narrate",
            "--cif-dir",
            str(tmp_path),
            "--provider",
            "mock",
            "--country",
            "US",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    # default version_id = provider name
    assert (tmp_path / "narratives/mock/documents/ENC-1/doc-1.json").exists()
    manifest = json.loads((tmp_path / "narratives/mock/manifest.json").read_text())
    assert manifest["generator"] == "llm-mock"
    # M-3: LLM providers do NOT repoint production exports by default
    assert not (tmp_path / "narratives/current_version.txt").exists()


# === M-3 (N-chain adv-1): --set-current tri-state default ===


@pytest.mark.unit
def test_narrate_mock_default_does_not_repoint_existing_pointer(tmp_path):
    """M-3 pin: a mock/LLM trial without flags must NOT silently repoint
    current_version.txt — a subsequent export-fhir (default "current") would
    emit mock narratives in a production export."""
    _write_tiny_structural(tmp_path)
    (tmp_path / "narratives").mkdir(exist_ok=True)
    (tmp_path / "narratives" / "current_version.txt").write_text("template")
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "narrate",
            "--cif-dir",
            str(tmp_path),
            "--provider",
            "mock",
            "--country",
            "US",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    pointer = (tmp_path / "narratives/current_version.txt").read_text().strip()
    assert pointer == "template"  # untouched
    assert "current ->" not in r.stdout


@pytest.mark.unit
def test_narrate_mock_explicit_set_current_updates_pointer(tmp_path):
    """M-3: explicit --set-current always wins, even for LLM providers."""
    _write_tiny_structural(tmp_path)
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "narrate",
            "--cif-dir",
            str(tmp_path),
            "--provider",
            "mock",
            "--country",
            "US",
            "--set-current",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    pointer = (tmp_path / "narratives/current_version.txt").read_text().strip()
    assert pointer == "mock"
    assert "current -> mock" in r.stdout


# === I-1 (chain 1b adv-1): partial (--patient-filter) run guards ===


def _narrate(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "narrate",
            "--cif-dir",
            str(tmp_path),
            "--country",
            "US",
            *extra,
        ],
        capture_output=True,
        text=True,
    )


@pytest.mark.unit
def test_narrate_filtered_default_does_not_set_current(tmp_path):
    """I-1(a) pin: with --patient-filter, the set-current default resolves to
    False for ALL providers (template included) — a partial run must never
    silently become 'current' for export-fhir."""
    _write_tiny_structural(tmp_path)
    r = _narrate(tmp_path, "--provider", "template", "--patient-filter", "ENC-1")
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / "narratives/current_version.txt").exists()
    assert "current ->" not in r.stdout


@pytest.mark.unit
def test_narrate_filtered_explicit_set_current_warns(tmp_path):
    """I-1: explicit --set-current with a filter proceeds but warns loudly."""
    _write_tiny_structural(tmp_path)
    r = _narrate(
        tmp_path,
        "--provider",
        "template",
        "--patient-filter",
        "ENC-1",
        "--set-current",
    )
    assert r.returncode == 0, r.stderr
    pointer = (tmp_path / "narratives/current_version.txt").read_text().strip()
    assert pointer == "template"
    assert "WARNING" in r.stderr and "partial" in r.stderr


@pytest.mark.unit
def test_narrate_filtered_into_existing_version_refused(tmp_path):
    """I-1(b) pin: a filtered write into a version dir that already contains
    documents is refused (stale mixed-generation files) without
    --merge-into-version."""
    _write_tiny_structural(tmp_path)
    full = _narrate(tmp_path, "--provider", "template", "--no-set-current")
    assert full.returncode == 0, full.stderr
    manifest_before = (tmp_path / "narratives/template/manifest.json").read_text()
    r = _narrate(tmp_path, "--provider", "template", "--patient-filter", "ENC-1")
    assert r.returncode != 0
    assert "--merge-into-version" in r.stderr
    # Refusal happens before the pass runs: manifest untouched
    assert (tmp_path / "narratives/template/manifest.json").read_text() == manifest_before


@pytest.mark.unit
def test_narrate_filtered_merge_into_version_opt_in(tmp_path):
    """I-1: --merge-into-version opts in to the iterate-one-patient loop,
    with a notice that mixed-generation files may coexist."""
    _write_tiny_structural(tmp_path)
    full = _narrate(tmp_path, "--provider", "template", "--no-set-current")
    assert full.returncode == 0, full.stderr
    r = _narrate(
        tmp_path,
        "--provider",
        "template",
        "--patient-filter",
        "ENC-1",
        "--merge-into-version",
    )
    assert r.returncode == 0, r.stderr
    assert "NOTICE" in r.stderr
    assert (tmp_path / "narratives/template/documents/ENC-1").exists()


@pytest.mark.unit
def test_narrate_filtered_fresh_version_needs_no_flag(tmp_path):
    """I-1: a filtered run into a fresh (or empty) version dir needs no flag."""
    _write_tiny_structural(tmp_path)
    r = _narrate(
        tmp_path,
        "--provider",
        "template",
        "--version-id",
        "trial-1",
        "--patient-filter",
        "ENC-1",
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "narratives/trial-1/documents/ENC-1").exists()


@pytest.mark.unit
def test_narrate_manifest_partial_flag(tmp_path):
    """I-1: the manifest records partial=true for filtered runs, false else."""
    _write_tiny_structural(tmp_path)
    r = _narrate(
        tmp_path,
        "--provider",
        "template",
        "--version-id",
        "trial-1",
        "--patient-filter",
        "ENC-1",
    )
    assert r.returncode == 0, r.stderr
    partial = json.loads((tmp_path / "narratives/trial-1/manifest.json").read_text())
    assert partial["partial"] is True
    assert partial["patient_filter"] == "ENC-1"
    full = _narrate(tmp_path, "--provider", "template", "--no-set-current")
    assert full.returncode == 0, full.stderr
    manifest = json.loads((tmp_path / "narratives/template/manifest.json").read_text())
    assert manifest["partial"] is False
