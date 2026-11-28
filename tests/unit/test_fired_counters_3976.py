"""Fired counters (Issue #3976): RNG-neutral, outside CIF and FHIR, reset per run."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from clinosim import fired_counters

_MODULE = Path(fired_counters.__file__)


@pytest.fixture(autouse=True)
def _clean_counters():
    fired_counters.reset()
    yield
    fired_counters.reset()


@pytest.mark.unit
def test_count_adds_and_respects_when():
    fired_counters.count("a.b")
    fired_counters.count("a.b", 2)
    fired_counters.count("a.c", when=False)
    fired_counters.count("a.d", 0)
    fired_counters.count_each("x", ["one", "two", "one"])
    assert fired_counters.snapshot() == {"a.b": 3, "x.one": 2, "x.two": 1}


@pytest.mark.unit
def test_reset_forgets_every_count():
    fired_counters.count("p")
    snap = fired_counters.snapshot()
    fired_counters.reset()
    assert snap == {"p": 1}
    assert fired_counters.snapshot() == {}


@pytest.mark.unit
def test_module_imports_no_rng_and_nothing_from_clinosim():
    """The counter module cannot touch a random stream: it imports only the
    standard library modules below and no clinosim, numpy or random module."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "collections"}


def _write_forced_cif(tmp_path: Path, name: str) -> dict[str, bytes]:
    from clinosim.modules.output.cif_writer import write_cif
    from clinosim.simulator.engine import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    dataset = run_forced(
        ForcedScenario(disease_id="urinary_tract_infection", severity="moderate", archetype="smooth_recovery"),
        SimulatorConfig(random_seed=7, country="US"),
    )
    out = tmp_path / name
    write_cif(dataset, str(out))
    return {
        str(p.relative_to(out)): p.read_bytes()
        for p in sorted(out.rglob("*"))
        if p.is_file() and p.name != "metadata.json"
    }


@pytest.mark.unit
def test_counters_fire_in_a_run_and_stay_out_of_the_cif(tmp_path):
    """A forced stay fires counters; the CIF is the same whatever the counters
    held before the run (``run_forced`` resets them), and no counter name is
    written into it."""
    first = _write_forced_cif(tmp_path, "a")
    fired = fired_counters.snapshot()
    assert fired, "a forced inpatient stay fires at least one counter"
    fired_counters.count("junk.left.over", 99)
    second = _write_forced_cif(tmp_path, "b")
    assert "junk.left.over" not in fired_counters.snapshot()
    assert first == second
    blob = b"".join(first.values())
    for path in fired:
        assert path.encode() not in blob
