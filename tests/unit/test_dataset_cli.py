"""P1-6 (session 46) — clinosim dataset subcommand unit tests.

Covers the pure-Python surface of ``clinosim.dataset``: preset discovery,
spec validation, generate-argv expansion, and the CLI dispatch entry
points. Actually running ``clinosim generate`` on the presets is not
exercised here — that's what
``tests/integration/test_full_reproducibility.py`` does at the shell
level once per locale.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.dataset import (
    DatasetPreset,
    list_presets,
    load_preset,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRESETS_DIR = _REPO_ROOT / "datasets"
_EXPECTED_PRESETS = ("us-100", "us-1000", "jp-100", "jp-1000")


@pytest.mark.unit
def test_expected_presets_discoverable() -> None:
    """The four presets P1-6 promised must all be discoverable."""
    names = list_presets()
    for expected in _EXPECTED_PRESETS:
        assert expected in names, f"preset {expected!r} missing under {_PRESETS_DIR} — discovered: {names}"


@pytest.mark.unit
@pytest.mark.parametrize("name", _EXPECTED_PRESETS)
def test_preset_loads_and_matches_directory(name: str) -> None:
    """Every preset spec must load cleanly and declare a matching ``name``."""
    preset = load_preset(name)
    assert isinstance(preset, DatasetPreset)
    assert preset.name == name, f"spec.yaml declares name={preset.name!r} but directory is {name!r}"
    # All P1-6 presets seed at 42 (contract in datasets/README.md).
    assert preset.seed == 42


@pytest.mark.unit
@pytest.mark.parametrize("name", _EXPECTED_PRESETS)
def test_preset_as_generate_args_shape(name: str) -> None:
    """as_generate_args must produce a valid `clinosim generate ...` argv."""
    preset = load_preset(name)
    argv = preset.as_generate_args("/tmp/output-dir")
    # First token is the subcommand.
    assert argv[0] == "generate"
    # Every flag has a value — pairs should be even.
    assert "--country" in argv and argv[argv.index("--country") + 1] == preset.country
    assert "--population" in argv and argv[argv.index("--population") + 1] == str(preset.population)
    assert "--seed" in argv and argv[argv.index("--seed") + 1] == "42"
    assert "--start" in argv and argv[argv.index("--start") + 1] == preset.start
    assert "--end" in argv and argv[argv.index("--end") + 1] == preset.end
    assert "--output" in argv and argv[argv.index("--output") + 1] == "/tmp/output-dir"
    assert "--format" in argv and argv[argv.index("--format") + 1] == preset.format


@pytest.mark.unit
def test_unknown_preset_raises_helpful_error() -> None:
    """Requesting a non-existent preset must raise ValueError listing what IS available."""
    with pytest.raises(ValueError) as exc_info:
        load_preset("does-not-exist")
    msg = str(exc_info.value)
    assert "does-not-exist" in msg
    # Should list at least one real preset in the error.
    assert any(p in msg for p in _EXPECTED_PRESETS), f"error message should list available presets: {msg}"


@pytest.mark.unit
def test_preset_directory_name_must_match_spec_name(tmp_path: Path) -> None:
    """A spec.yaml declaring a different `name` than its directory must fail."""
    d = tmp_path / "mismatch"
    d.mkdir()
    (d / "spec.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "different-name",  # intentionally not "mismatch"
                "description": "test",
                "country": "US",
                "population": 10,
                "seed": 42,
                "start": "2026-01-01",
                "end": "2026-01-31",
                "format": "fhir",
            }
        )
    )
    with pytest.raises(ValueError, match="directory name and spec name must match"):
        load_preset("mismatch", presets_dir=tmp_path)


@pytest.mark.unit
def test_missing_spec_key_raises_specific_error(tmp_path: Path) -> None:
    """Absent required key must be surfaced clearly — not KeyError with a
    single field name."""
    d = tmp_path / "partial"
    d.mkdir()
    (d / "spec.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "partial",
                "description": "test",
                # missing: country, population, seed, start, end, format
            }
        )
    )
    with pytest.raises(ValueError, match="missing required key"):
        load_preset("partial", presets_dir=tmp_path)


@pytest.mark.unit
def test_cli_subcommand_registered() -> None:
    """`clinosim dataset --help` must be reachable via the entry point."""
    from importlib import metadata

    try:
        metadata.distribution("clinosim")
    except metadata.PackageNotFoundError:
        pytest.skip("clinosim not installed")

    # Verify the top-level parser has a `dataset` subcommand by importing
    # the module and constructing a parser — cheaper than shelling out.
    import argparse

    from clinosim.dataset import add_dataset_subparser

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    add_dataset_subparser(sub)

    args = parser.parse_args(["dataset", "list"])
    assert args.command == "dataset"
    assert args.dataset_command == "list"

    args = parser.parse_args(["dataset", "build", "jp-100", "-o", "/tmp/out"])
    assert args.command == "dataset"
    assert args.dataset_command == "build"
    assert args.name == "jp-100"
    assert args.output == "/tmp/out"
