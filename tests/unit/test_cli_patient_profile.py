"""AD-66 α-min-2c T2: test-disease --patient-profile CLI wiring tests."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def _write_profile(tmp_path: Path, name: str, data: dict) -> Path:
    """Helper: write a YAML profile file under tmp_path."""
    yaml_path = tmp_path / f"{name}.yaml"
    yaml_path.write_text(yaml.safe_dump(data))
    return yaml_path


def test_test_disease_help_mentions_patient_profile():
    """`clinosim test-disease --help` includes --patient-profile."""
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert "--patient-profile" in result.stdout


def test_positional_disease_id_optional_with_profile(tmp_path: Path):
    """`test-disease --patient-profile PATH -o OUT` works without positional disease_id."""
    profile_path = _write_profile(tmp_path, "smoke_test", {
        "profile_id": "smoke_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "--patient-profile", str(profile_path),
         "--format", "cif", "-o", str(out_dir)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    # Verify CIF structural output exists
    assert (out_dir / "cif" / "structural" / "patients").is_dir()


def test_cli_severity_overrides_profile_with_warn(tmp_path: Path):
    """When --severity differs from profile.severity, CLI wins + stderr warns."""
    profile_path = _write_profile(tmp_path, "override_test", {
        "profile_id": "override_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "mild",
        "count": 1,
        "random_seed": 42,
    })
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "--patient-profile", str(profile_path),
         "--severity", "severe",
         "--format", "cif", "-o", str(out_dir)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "WARN" in result.stderr or "warn" in result.stderr.lower()
    assert "severity" in result.stderr.lower()


def test_positional_disease_id_overrides_profile_with_warn(tmp_path: Path):
    """When positional differs from profile.disease_id, positional wins + warn."""
    profile_path = _write_profile(tmp_path, "disease_override", {
        "profile_id": "disease_override",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "sepsis",
         "--patient-profile", str(profile_path),
         "--format", "cif", "-o", str(out_dir)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "WARN" in result.stderr or "warn" in result.stderr.lower()
    assert "disease" in result.stderr.lower()


def test_missing_profile_exits_2_with_message(tmp_path: Path):
    """--patient-profile nonexistent → sys.exit(2) with actionable error."""
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
         "--patient-profile", "nonexistent_profile_xyz_12345",
         "--format", "cif", "-o", str(out_dir)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2, f"expected exit 2, got {result.returncode}"
    assert (
        "nonexistent_profile_xyz_12345" in result.stderr
        or "not found" in result.stderr.lower()
    )


def test_same_profile_produces_deterministic_narrative(tmp_path: Path):
    """Two runs with the same profile + seed produce byte-identical NARRATIVE output.

    Structural CIF has pre-existing wall-clock nondeterminism (issue_date,
    MAR timestamps) unrelated to α-min-2c scope. Narrative output uses
    _deterministic_timestamp (AD-16 discipline, PR #131 F-5 preserved)
    so template narrative regression is byte-diff-stable.
    """
    profile_path = _write_profile(tmp_path, "determinism_test", {
        "profile_id": "determinism_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    for out in (out1, out2):
        subprocess.run(
            [sys.executable, "-m", "clinosim.simulator.cli", "test-disease",
             "--patient-profile", str(profile_path),
             "--format", "cif", "-o", str(out)],
            capture_output=True, text=True, check=True,
        )
    narr1 = out1 / "cif" / "narratives" / "template" / "documents"
    narr2 = out2 / "cif" / "narratives" / "template" / "documents"
    assert narr1.is_dir() and narr2.is_dir()
    # Walk narrative files, compare byte-identity
    files1 = sorted(narr1.rglob("*.json"))
    files2 = sorted(narr2.rglob("*.json"))
    assert len(files1) == len(files2) and len(files1) > 0
    for f1, f2 in zip(files1, files2):
        assert f1.read_text() == f2.read_text(), (
            f"Narrative diverged for {f1.relative_to(narr1)}"
        )
