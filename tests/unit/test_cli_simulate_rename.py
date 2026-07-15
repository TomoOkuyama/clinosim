"""session 48 cleanup (g): CLI `generate` → `simulate` rename テスト.

- `simulate` は canonical、正常起動
- `generate` は deprecation alias、実行はできるが stderr に警告
- 両方から同じ population echo が出る(=同じ handler が dispatch される)
"""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.unit
def test_simulate_command_runs(tmp_path):
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "simulate",
            "-p",
            "7",
            "--country",
            "US",
            "-o",
            str(tmp_path),
            "--format",
            "cif",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert "population=7" in r.stdout


@pytest.mark.unit
def test_generate_alias_still_works(tmp_path):
    """後方互換:`generate` を打つと handler は同一で正常終了する。"""
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "generate",
            "-p",
            "7",
            "--country",
            "US",
            "-o",
            str(tmp_path),
            "--format",
            "cif",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert "population=7" in r.stdout


@pytest.mark.unit
def test_generate_alias_emits_deprecation_warning(tmp_path):
    """`generate` 使用時は stderr に "DeprecationWarning" を含む警告が出る。"""
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "generate",
            "-p",
            "7",
            "--country",
            "US",
            "-o",
            str(tmp_path),
            "--format",
            "cif",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0
    assert "DeprecationWarning" in r.stderr
    assert "'generate'" in r.stderr
    assert "'simulate'" in r.stderr


@pytest.mark.unit
def test_simulate_no_deprecation_warning(tmp_path):
    """`simulate`(canonical)使用時は deprecation warning が出ない。"""
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "simulate",
            "-p",
            "7",
            "--country",
            "US",
            "-o",
            str(tmp_path),
            "--format",
            "cif",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0
    assert "DeprecationWarning" not in r.stderr


@pytest.mark.unit
def test_help_lists_simulate_as_primary():
    """--help に simulate + generate 両方が subcommand として登場する。"""
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0
    assert "simulate" in r.stdout
    assert "generate" in r.stdout
