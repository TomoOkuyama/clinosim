"""Every test directory is run by a CI workflow, and CI lints with the dev ruff.

`tests/e2e` was run by no workflow until Issue #3070, and `tests/simulator`
by none until it joined the unit job, so failures there went unnoticed. This
guard reads the `pytest` commands of the PR and nightly workflows and fails
when a top-level test directory (or an e2e file, since e2e is split between
the two workflows by file) is not on any of them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOWS = ("ci.yml", "nightly.yml")
_PYTEST_ARGS = re.compile(r"pytest((?:\s+tests/[\w./-]+)+)")


def _pytest_targets() -> set[str]:
    targets: set[str] = set()
    for name in _WORKFLOWS:
        text = (_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        # Folded (`>`) run blocks put arguments on continuation lines.
        flat = re.sub(r"\n\s+", " ", text)
        for match in _PYTEST_ARGS.finditer(flat):
            targets.update(arg.rstrip("/") for arg in match.group(1).split())
    return targets


def _covered(path: str, targets: set[str]) -> bool:
    return any(path == t or path.startswith(t + "/") for t in targets)


def test_every_test_directory_is_run_by_a_workflow() -> None:
    targets = _pytest_targets()
    dirs = sorted(
        f"tests/{d.name}"
        for d in (_ROOT / "tests").iterdir()
        if d.is_dir() and d.name != "e2e" and any(d.rglob("test_*.py"))
    )
    missing = [d for d in dirs if not _covered(d, targets)]
    assert not missing, f"test directories run by no workflow ({', '.join(_WORKFLOWS)}): {missing}"


def test_every_e2e_file_is_run_by_a_workflow() -> None:
    targets = _pytest_targets()
    files = sorted(str(p.relative_to(_ROOT)) for p in (_ROOT / "tests" / "e2e").rglob("test_*.py"))
    missing = [f for f in files if not _covered(f, targets)]
    assert not missing, f"e2e files run by no workflow ({', '.join(_WORKFLOWS)}): {missing}"


def test_ci_ruff_pin_matches_pyproject() -> None:
    """The CI quality job and the dev extras install the same ruff, so a lint
    or format failure reproduces locally (CI once pinned 0.17.1 while the dev
    extras pinned 0.17.3)."""
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    ci_pins = set(re.findall(r'"ruff==([\d.]+)"', ci))
    dev_pins = set(re.findall(r'"ruff==([\d.]+)"', pyproject))
    assert ci_pins and ci_pins == dev_pins, f"ci.yml ruff {ci_pins} != pyproject.toml ruff {dev_pins}"
