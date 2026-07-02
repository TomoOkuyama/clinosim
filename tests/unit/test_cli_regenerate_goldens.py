"""AD-66 α-min-2c T3: regenerate-goldens CLI unit tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def _write_profile(fixture_dir: Path, name: str, data: dict) -> Path:
    yaml_path = fixture_dir / f"{name}.yaml"
    yaml_path.write_text(yaml.safe_dump(data))
    return yaml_path


def _env_with(fixture_dir: Path) -> dict[str, str]:
    return {**os.environ, "CLINOSIM_PATIENT_PROFILE_DIR": str(fixture_dir)}


def test_regenerate_goldens_help():
    """`clinosim regenerate-goldens --help` mentions --profile and --all."""
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "--profile" in result.stdout
    assert "--all" in result.stdout


def test_regenerate_single_profile(tmp_path: Path):
    """--profile <name> writes <name>.golden.json in the fixture dir."""
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    _write_profile(fixture_dir, "single_test", {
        "profile_id": "single_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })

    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "single_test"],
        capture_output=True, text=True, check=False,
        env=_env_with(fixture_dir),
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    golden_path = fixture_dir / "single_test.golden.json"
    assert golden_path.is_file(), "golden JSON not written"
    golden = json.loads(golden_path.read_text())
    assert isinstance(golden, dict), "golden should be document_id → narrative_dict"


def test_regenerate_all_profiles(tmp_path: Path):
    """--all iterates every YAML in the fixture dir."""
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    for name in ("all_test_a", "all_test_b"):
        _write_profile(fixture_dir, name, {
            "profile_id": name,
            "disease_id": "bacterial_pneumonia",
            "country": "US",
            "severity": "moderate",
            "count": 1,
            "random_seed": 42,
        })

    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens", "--all"],
        capture_output=True, text=True, check=False,
        env=_env_with(fixture_dir),
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert (fixture_dir / "all_test_a.golden.json").is_file()
    assert (fixture_dir / "all_test_b.golden.json").is_file()


def test_profile_and_all_mutually_exclusive(tmp_path: Path):
    """--profile and --all are mutually exclusive."""
    result = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "x", "--all"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "not allowed" in result.stderr.lower() or "argument" in result.stderr.lower()


def test_regenerate_is_idempotent(tmp_path: Path):
    """Running --profile twice yields byte-identical golden."""
    fixture_dir = tmp_path / "patient_profiles"
    fixture_dir.mkdir()
    _write_profile(fixture_dir, "idem_test", {
        "profile_id": "idem_test",
        "disease_id": "bacterial_pneumonia",
        "country": "US",
        "severity": "moderate",
        "count": 1,
        "random_seed": 42,
    })
    env = _env_with(fixture_dir)

    subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "idem_test"],
        env=env, capture_output=True, text=True, check=True,
    )
    first = (fixture_dir / "idem_test.golden.json").read_text()

    subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "regenerate-goldens",
         "--profile", "idem_test"],
        env=env, capture_output=True, text=True, check=True,
    )
    second = (fixture_dir / "idem_test.golden.json").read_text()

    assert first == second, "regenerate-goldens is not idempotent (byte-diff between two runs)"
