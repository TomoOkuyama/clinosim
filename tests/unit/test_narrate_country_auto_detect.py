"""narrate CLI: `--country` auto-detects from `cif/metadata.json`.

Regression guard for the session-97 verify finding — a JP-generated CIF
that was narrated without `--country JP` silently produced 34,908
English-language sections against JA structural data because the CLI
default was `--country US`. Post-fix (`_resolve_narrate_country`):

  * cif/metadata.json present and `--country` omitted → use metadata's
    country (JP CIF renders JA narratives without extra flags).
  * cif/metadata.json present and `--country` matches → honored.
  * cif/metadata.json present and `--country` mismatches → EXIT 2 with
    a helpful message (the caller almost certainly does not want
    wrong-language narratives against the structural CIF).
  * cif/metadata.json absent (legacy CIF) → fall back to `--country`
    value (default `US`) with a stderr warning.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _write_metadata(cif_dir: Path, country: str) -> None:
    (cif_dir / "metadata.json").write_text(
        json.dumps({"country": country, "clinosim_version": "0.5.0"}, ensure_ascii=False)
    )


def _mkargs(cif_dir: Path, country: str = "") -> SimpleNamespace:
    return SimpleNamespace(cif_dir=str(cif_dir), country=country)


@pytest.mark.unit
def test_country_read_from_cif_metadata_jp(tmp_path: Path) -> None:
    from clinosim.simulator.cli_narrate import _country_from_cif_metadata

    _write_metadata(tmp_path, "JP")
    assert _country_from_cif_metadata(str(tmp_path)) == "JP"


@pytest.mark.unit
def test_country_read_from_cif_metadata_us(tmp_path: Path) -> None:
    from clinosim.simulator.cli_narrate import _country_from_cif_metadata

    _write_metadata(tmp_path, "us")  # lower-case in yaml — normalize to upper
    assert _country_from_cif_metadata(str(tmp_path)) == "US"


@pytest.mark.unit
def test_country_read_none_when_metadata_missing(tmp_path: Path) -> None:
    from clinosim.simulator.cli_narrate import _country_from_cif_metadata

    assert _country_from_cif_metadata(str(tmp_path)) is None


@pytest.mark.unit
def test_country_read_none_when_metadata_malformed(tmp_path: Path) -> None:
    from clinosim.simulator.cli_narrate import _country_from_cif_metadata

    (tmp_path / "metadata.json").write_text("{not valid json")
    assert _country_from_cif_metadata(str(tmp_path)) is None


@pytest.mark.unit
def test_resolve_country_prefers_cif_metadata_when_cli_default(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """CLI default (empty sentinel) + JP metadata → JP is used (no confirmation
    printed; this is the whole point of the auto-detect fix)."""
    from clinosim.simulator.cli_narrate import _resolve_narrate_country

    _write_metadata(tmp_path, "JP")
    resolved = _resolve_narrate_country(_mkargs(tmp_path, country=""))
    assert resolved == "JP"
    err = capsys.readouterr().err
    assert "NOTICE" not in err


@pytest.mark.unit
def test_resolve_country_explicit_cli_matching_metadata_ok(tmp_path: Path) -> None:
    from clinosim.simulator.cli_narrate import _resolve_narrate_country

    _write_metadata(tmp_path, "JP")
    assert _resolve_narrate_country(_mkargs(tmp_path, country="JP")) == "JP"


@pytest.mark.unit
def test_resolve_country_explicit_cli_mismatching_metadata_fails_loud(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Explicit --country US on a JP CIF must EXIT 2 (SystemExit) with a
    helpful error message on stderr. This is the regression guard for the
    silent-wrong-language failure mode that motivated the auto-detect
    fix."""
    from clinosim.simulator.cli_narrate import _resolve_narrate_country

    _write_metadata(tmp_path, "JP")
    with pytest.raises(SystemExit) as excinfo:
        _resolve_narrate_country(_mkargs(tmp_path, country="US"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "ERROR" in err
    assert "JP" in err
    assert "US" in err
    assert "cif/metadata.json" in err


@pytest.mark.unit
def test_resolve_country_missing_metadata_falls_back_to_cli(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Legacy CIF (no metadata.json) → CLI value is used with a stderr NOTICE
    so the caller sees the fallback."""
    from clinosim.simulator.cli_narrate import _resolve_narrate_country

    resolved = _resolve_narrate_country(_mkargs(tmp_path, country="JP"))
    assert resolved == "JP"
    err = capsys.readouterr().err
    assert "NOTICE" in err
    assert "cif/metadata.json not found" in err


@pytest.mark.unit
def test_resolve_country_missing_metadata_and_no_cli_defaults_to_us(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Legacy CIF + no --country → falls all the way through to the
    documented default US, with the same warning."""
    from clinosim.simulator.cli_narrate import _resolve_narrate_country

    resolved = _resolve_narrate_country(_mkargs(tmp_path, country=""))
    assert resolved == "US"
    err = capsys.readouterr().err
    assert "NOTICE" in err
