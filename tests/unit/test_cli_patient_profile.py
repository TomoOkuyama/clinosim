"""AD-66 α-min-2c T2: test-disease --patient-profile CLI wiring tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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
        capture_output=True,
        text=True,
        check=False,
    )
    assert "--patient-profile" in result.stdout


def test_positional_disease_id_optional_with_profile(tmp_path: Path):
    """`test-disease --patient-profile PATH -o OUT` works without positional disease_id."""
    profile_path = _write_profile(
        tmp_path,
        "smoke_test",
        {
            "profile_id": "smoke_test",
            "disease_id": "bacterial_pneumonia",
            "country": "US",
            "severity": "moderate",
            "count": 1,
            "random_seed": 42,
        },
    )
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "test-disease",
            "--patient-profile",
            str(profile_path),
            "--format",
            "cif",
            "-o",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    # Verify CIF structural output exists
    assert (out_dir / "cif" / "structural" / "patients").is_dir()


def test_cli_severity_overrides_profile_with_warn(tmp_path: Path):
    """When --severity differs from profile.severity, CLI wins + stderr warns."""
    profile_path = _write_profile(
        tmp_path,
        "override_test",
        {
            "profile_id": "override_test",
            "disease_id": "bacterial_pneumonia",
            "country": "US",
            "severity": "mild",
            "count": 1,
            "random_seed": 42,
        },
    )
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "test-disease",
            "--patient-profile",
            str(profile_path),
            "--severity",
            "severe",
            "--format",
            "cif",
            "-o",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "WARN" in result.stderr or "warn" in result.stderr.lower()
    assert "severity" in result.stderr.lower()


def test_positional_disease_id_overrides_profile_with_warn(tmp_path: Path):
    """When positional differs from profile.disease_id, positional wins + warn."""
    profile_path = _write_profile(
        tmp_path,
        "disease_override",
        {
            "profile_id": "disease_override",
            "disease_id": "bacterial_pneumonia",
            "country": "US",
            "severity": "moderate",
            "count": 1,
            "random_seed": 42,
        },
    )
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "test-disease",
            "sepsis",
            "--patient-profile",
            str(profile_path),
            "--format",
            "cif",
            "-o",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "WARN" in result.stderr or "warn" in result.stderr.lower()
    assert "disease" in result.stderr.lower()


def test_missing_profile_exits_2_with_message(tmp_path: Path):
    """--patient-profile nonexistent → sys.exit(2) with actionable error."""
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "test-disease",
            "--patient-profile",
            "nonexistent_profile_xyz_12345",
            "--format",
            "cif",
            "-o",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, f"expected exit 2, got {result.returncode}"
    assert "nonexistent_profile_xyz_12345" in result.stderr or "not found" in result.stderr.lower()


def test_same_profile_produces_deterministic_narrative(tmp_path: Path):
    """Two runs with the same profile + seed produce byte-identical NARRATIVE output.

    Structural CIF has pre-existing wall-clock nondeterminism (issue_date,
    MAR timestamps) unrelated to α-min-2c scope. Narrative output uses
    _deterministic_timestamp (AD-16 discipline, PR #131 F-5 preserved)
    so template narrative regression is byte-diff-stable.
    """
    profile_path = _write_profile(
        tmp_path,
        "determinism_test",
        {
            "profile_id": "determinism_test",
            "disease_id": "bacterial_pneumonia",
            "country": "US",
            "severity": "moderate",
            "count": 1,
            "random_seed": 42,
        },
    )
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    for out in (out1, out2):
        subprocess.run(
            [
                sys.executable,
                "-m",
                "clinosim.simulator.cli",
                "test-disease",
                "--patient-profile",
                str(profile_path),
                "--format",
                "cif",
                "-o",
                str(out),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    narr1 = out1 / "cif" / "narratives" / "template" / "documents"
    narr2 = out2 / "cif" / "narratives" / "template" / "documents"
    assert narr1.is_dir() and narr2.is_dir()
    # Walk narrative files, compare byte-identity
    files1 = sorted(narr1.rglob("*.json"))
    files2 = sorted(narr2.rglob("*.json"))
    assert len(files1) == len(files2) and len(files1) > 0
    for f1, f2 in zip(files1, files2):
        assert f1.read_text() == f2.read_text(), f"Narrative diverged for {f1.relative_to(narr1)}"


# --- adv-1 F-2: sentinel-default CLI override resolution ---


def _make_args(**kwargs) -> SimpleNamespace:
    """Args namespace mirroring the test-disease subparser (F-2: None defaults)."""
    base = dict(
        disease_id=None,
        patient_profile=None,
        count=None,
        severity=None,
        archetype=None,
        seed=None,
        country=None,
        format=None,
        output=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _make_profile(**kwargs):
    from clinosim.types.config import PatientProfile

    base = dict(
        profile_id="helper_test",
        disease_id="bacterial_pneumonia",
        country="US",
        severity="moderate",
        count=1,
        random_seed=99,
    )
    base.update(kwargs)
    return PatientProfile(**base)


def test_explicit_seed_equal_to_legacy_default_overrides_profile(
    capsys: pytest.CaptureFixture,
):
    """--seed 42 (== old argparse default) vs profile seed 99 → CLI wins + WARN.

    Pre-F-2 defect: `if args.seed != 42` made an explicit `--seed 42`
    indistinguishable from "flag omitted", so it silently lost to the profile.
    """
    from clinosim.simulator.cli import _apply_profile_cli_overrides

    resolved = _apply_profile_cli_overrides(_make_args(seed=42), _make_profile(random_seed=99))
    assert resolved.random_seed == 42
    stderr = capsys.readouterr().err
    assert "WARN" in stderr and "seed" in stderr.lower()


def test_explicit_country_equal_to_legacy_default_overrides_profile(
    capsys: pytest.CaptureFixture,
):
    """--country US (== old argparse default) vs profile country JP → CLI wins + WARN."""
    from clinosim.simulator.cli import _apply_profile_cli_overrides

    resolved = _apply_profile_cli_overrides(_make_args(country="US"), _make_profile(country="JP"))
    assert resolved.country == "US"
    stderr = capsys.readouterr().err
    assert "WARN" in stderr and "country" in stderr.lower()


def test_omitted_cli_flags_use_profile_values(capsys: pytest.CaptureFixture):
    """No CLI flags (all None) → profile values win untouched, no WARN."""
    from clinosim.simulator.cli import _apply_profile_cli_overrides

    profile = _make_profile(country="JP", random_seed=99, count=2)
    resolved = _apply_profile_cli_overrides(_make_args(), profile)
    assert resolved == profile
    assert "WARN" not in capsys.readouterr().err


def test_cli_value_equal_to_profile_value_is_silent(capsys: pytest.CaptureFixture):
    """Explicit CLI value equal to the profile value → used, but no WARN noise."""
    from clinosim.simulator.cli import _apply_profile_cli_overrides

    resolved = _apply_profile_cli_overrides(
        _make_args(seed=99, country="JP"), _make_profile(random_seed=99, country="JP")
    )
    assert resolved.random_seed == 99 and resolved.country == "JP"
    assert "WARN" not in capsys.readouterr().err


def test_count_overrides_profile_with_warn(capsys: pytest.CaptureFixture):
    """-n/--count overrides profile count with WARN (pre-F-2: silently ignored)."""
    from clinosim.simulator.cli import _apply_profile_cli_overrides

    resolved = _apply_profile_cli_overrides(_make_args(count=2), _make_profile(count=1))
    assert resolved.count == 2
    stderr = capsys.readouterr().err
    assert "WARN" in stderr and "count" in stderr.lower()


def test_no_profile_applies_legacy_defaults():
    """Non-profile mode: omitted flags resolve to the old defaults (3 / 42 / US)."""
    from clinosim.simulator.cli import _resolve_test_disease_defaults

    args = _make_args(disease_id="bacterial_pneumonia")
    _resolve_test_disease_defaults(args)
    assert args.count == 3
    assert args.seed == 42
    assert args.country == "US"

    # Explicit values are never touched
    args = _make_args(disease_id="sepsis", count=5, seed=7, country="JP")
    _resolve_test_disease_defaults(args)
    assert (args.count, args.seed, args.country) == (5, 7, "JP")


def test_cli_seed_42_overrides_profile_seed_end_to_end(tmp_path: Path):
    """Subprocess proof: profile random_seed=99 + explicit --seed 42 → metadata seed 42 + WARN."""
    profile_path = _write_profile(
        tmp_path,
        "seed_override_e2e",
        {
            "profile_id": "seed_override_e2e",
            "disease_id": "bacterial_pneumonia",
            "country": "US",
            "severity": "moderate",
            "count": 1,
            "random_seed": 99,
        },
    )
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "test-disease",
            "--patient-profile",
            str(profile_path),
            "--seed",
            "42",
            "--format",
            "cif",
            "-o",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "WARN" in result.stderr and "seed" in result.stderr.lower()
    metadata = json.loads((out_dir / "cif" / "metadata.json").read_text())
    assert metadata["random_seed"] == 42


def test_omitted_seed_uses_profile_seed_end_to_end(tmp_path: Path):
    """Subprocess proof: profile random_seed=99, no --seed → metadata seed 99, no WARN."""
    profile_path = _write_profile(
        tmp_path,
        "seed_profile_e2e",
        {
            "profile_id": "seed_profile_e2e",
            "disease_id": "bacterial_pneumonia",
            "country": "US",
            "severity": "moderate",
            "count": 1,
            "random_seed": 99,
        },
    )
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "test-disease",
            "--patient-profile",
            str(profile_path),
            "--format",
            "cif",
            "-o",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "WARN" not in result.stderr
    metadata = json.loads((out_dir / "cif" / "metadata.json").read_text())
    assert metadata["random_seed"] == 99
