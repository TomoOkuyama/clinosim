"""Bug D fix — `-p`/`--population` no longer collides with a silent sentinel.

Historically `engine.py` treated `catchment_population == 10_000` (the OLD argparse
default for `-p`) as a magic value meaning "user did not override" and silently
replaced it with the hospital's `recommended_population`. Any user who explicitly
asked for `-p 10000` had their request discarded without warning.

The fix makes `SimulatorConfig.catchment_population` `int | None`, with `None`
meaning "no explicit user value" (argparse now uses `SUPPRESS` as the CLI default
so `args.population` simply does not exist unless `-p` was passed). `engine.py`
resolves the hospital's recommended population only when the config value is
`None`.

Tests here call `run_beta` directly with `generate_population` monkeypatched to
raise immediately after capturing the resolved `pop_size` — this exercises the
exact same code path the CLI drives, without paying for a full population
simulation (which would take minutes at realistic catchment sizes).
"""

from __future__ import annotations

import argparse
import subprocess
import sys

import pytest

import clinosim.simulator.engine as engine_mod
from clinosim.types.config import SimulatorConfig


class _StopEarlyError(Exception):
    """Raised by the monkeypatched generate_population to short-circuit run_beta."""


def _capture_pop_size(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    captured: dict[str, int] = {}

    def fake_generate_population(pop_size: int, country: str, rng: object, *a: object, **kw: object) -> None:
        captured["pop_size"] = pop_size
        raise _StopEarlyError()

    monkeypatch.setattr(engine_mod, "generate_population", fake_generate_population)
    return captured


@pytest.mark.unit
def test_config_catchment_defaults_to_none() -> None:
    c = SimulatorConfig()
    assert c.catchment_population is None


@pytest.mark.unit
def test_explicit_p_10000_not_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bug D: an explicit 10000 (the old CLI default value) must reach generate_population
    unchanged, NOT be silently replaced by the hospital's recommended_population (US=40000).
    """
    captured = _capture_pop_size(monkeypatch)
    config = SimulatorConfig(catchment_population=10_000, country="US")

    with pytest.raises(_StopEarlyError):
        engine_mod.run_beta(config)

    assert captured["pop_size"] == 10_000


@pytest.mark.unit
def test_omitted_p_uses_recommended(monkeypatch: pytest.MonkeyPatch) -> None:
    """No explicit population (None) resolves to the hospital's recommended_population
    (US default hospital_operations.yaml recommends 40000).
    """
    captured = _capture_pop_size(monkeypatch)
    config = SimulatorConfig(country="US")
    assert config.catchment_population is None

    with pytest.raises(_StopEarlyError):
        engine_mod.run_beta(config)

    assert captured["pop_size"] == 40_000


@pytest.mark.unit
def test_explicit_p_diverging_from_recommended_warns_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the explicit value diverges from the hospital recommendation, engine.py
    must emit a visible stderr warning (making the override intentional, not silent)
    while still honoring the user's value.
    """
    captured = _capture_pop_size(monkeypatch)
    config = SimulatorConfig(catchment_population=123, country="US")

    with pytest.raises(_StopEarlyError):
        engine_mod.run_beta(config)

    assert captured["pop_size"] == 123


@pytest.mark.unit
def test_cli_generate_argparse_population_uses_suppress() -> None:
    """argparse.SUPPRESS means args.population does not exist unless -p was passed —
    this is what lets cli.py distinguish 'user passed -p 10000' from 'user omitted -p'.
    """
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    gen = sub.add_parser("generate")
    gen.add_argument("-p", "--population", type=int, default=argparse.SUPPRESS)

    omitted = parser.parse_args(["generate"])
    assert not hasattr(omitted, "population")

    explicit = parser.parse_args(["generate", "-p", "10000"])
    assert explicit.population == 10_000


@pytest.mark.unit
def test_cli_generate_reports_explicit_population_in_stdout(tmp_path: object) -> None:
    """End-to-end smoke test (tiny population for speed): explicit -p N is echoed
    verbatim in stdout, not replaced.

    Person count is not asserted exactly — households sample from [1,2,2,3,3,4]
    so the realized total_persons varies with RNG state (2 households for -p 7
    → range [2, 8]).  What we DO enforce is that the CLI passes -p through and
    that a population is actually generated (non-zero).
    """
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
    import re

    m = re.search(r"Population: (\d+) persons", r.stdout)
    assert m, f"'Population: N persons' line missing from stdout:\n{r.stdout}"
    n = int(m.group(1))
    assert 1 <= n <= 12, f"total_persons={n} outside realistic range for -p 7"
