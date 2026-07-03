"""β-JP-1 chain 1b T2 integration: mock profile pipeline → check-narratives green.

Spec §3 gate 5: test-disease (profile) → narrate --provider mock →
`check-narratives` exits 0 with the profile's shipped expectations; a
deliberately-broken expectations file exits 1; an invalid expectations file
exits 2. Runs the pipeline ONCE per module (subprocess latency) and shares
the CIF dir across the three CLI assertions.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROFILE_ID = "jp_inpatient_bacterial_pneumonia"
FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "patient_profiles"
VERSION = "llm-mock"


def _run_cli(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", *argv],
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def mock_cif_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One profile pipeline run + mock narrate, shared by all tests below."""
    out = tmp_path_factory.mktemp("check_narratives_mock")
    gen = _run_cli(
        "test-disease", "--patient-profile", str(FIXTURE_DIR / f"{PROFILE_ID}.yaml"),
        "--format", "cif", "-o", str(out),
    )
    assert gen.returncode == 0, gen.stderr
    cif_dir = out / "cif"
    narrate = _run_cli(
        "narrate", "--cif-dir", str(cif_dir), "--provider", "mock",
        "--country", "JP", "--seed", "42",
        "--version-id", VERSION, "--no-set-current",
    )
    assert narrate.returncode == 0, narrate.stderr
    return cif_dir


@pytest.mark.integration
def test_check_narratives_mock_pipeline_green(mock_cif_dir: Path, tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    result = _run_cli(
        "check-narratives", "--cif-dir", str(mock_cif_dir), "--version", VERSION,
        "--profile", PROFILE_ID, "--report", str(report_path),
    )
    assert result.returncode == 0, (
        f"check-narratives failed on the mock pipeline:\n{result.stdout}\n{result.stderr}"
    )
    assert "PASS" in result.stdout
    report = json.loads(report_path.read_text())
    assert report["passed"] is True
    assert report["document_count"] > 0
    assert report["info"]["generator"] == "llm-mock"
    # The mock exemption must have actually fired (llm sections skipped) —
    # otherwise the [Mock markers would have produced findings, and a future
    # regression that stops skipping would silently weaken this test.
    assert report["info"]["skipped_mock_llm_sections"] > 0


@pytest.mark.integration
def test_check_narratives_broken_expectations_exit_1(
    mock_cif_dir: Path, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.llm-expectations.yaml"
    broken.write_text(
        "discharge_summary:\n"
        "  discharge_diagnoses:\n"
        "    all_of: [\"この文言は絶対に出現しない\"]\n",
        encoding="utf-8",
    )
    result = _run_cli(
        "check-narratives", "--cif-dir", str(mock_cif_dir), "--version", VERSION,
        "--expectations", str(broken),
    )
    assert result.returncode == 1, f"expected findings exit 1:\n{result.stdout}"
    assert "phrase" in result.stdout


@pytest.mark.integration
def test_check_narratives_invalid_expectations_exit_2(
    mock_cif_dir: Path, tmp_path: Path
) -> None:
    invalid = tmp_path / "invalid.llm-expectations.yaml"
    invalid.write_text("no_such_doc_type:\n  text:\n    all_of: [\"x\"]\n")
    result = _run_cli(
        "check-narratives", "--cif-dir", str(mock_cif_dir), "--version", VERSION,
        "--expectations", str(invalid),
    )
    assert result.returncode == 2
    assert "invalid expectations" in result.stderr
