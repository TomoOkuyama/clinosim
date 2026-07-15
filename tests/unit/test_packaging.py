"""Session 46 P0 #1 packaging guards.

Two guarantees are asserted here:

1. **Single source of truth for the version.** The version string in
   ``clinosim/__init__.py::__version__`` is what ``pyproject.toml``'s
   ``[tool.hatch.version]`` reads at build time. If someone accidentally
   re-adds a hard-coded ``version =`` line to ``[project]`` the two can
   drift silently — PyPI would ship one number, ``clinosim.__version__``
   another. This test catches that.

2. **Console entry point is registered.** ``pip install .`` is only useful
   if the ``clinosim`` command is on PATH. We can't run the compiled binary
   from within a plain ``pytest`` (the shim only exists post-install), but
   ``importlib.metadata.entry_points`` sees the registered script whenever
   the project is installed in editable or wheel mode — which is the case
   in CI and any dev checkout that ran ``pip install -e``.
"""

from __future__ import annotations

import re
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

import clinosim

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


@pytest.mark.unit
def test_version_single_source_of_truth() -> None:
    """``clinosim.__version__`` and the version hatch reads from pyproject must
    agree, and no hard-coded ``version =`` line may exist in ``[project]``."""
    with _PYPROJECT.open("rb") as f:
        pyproject = tomllib.load(f)
    project = pyproject.get("project", {})

    # Rule A: [project] must NOT carry a static version key — hatch reads it
    # dynamically from clinosim/__init__.py. A static value would silently win.
    assert "version" not in project, (
        "pyproject.toml [project] must not set a static `version = ...`; "
        "version is dynamic and sourced from clinosim/__init__.py."
    )
    assert "version" in project.get("dynamic", []), 'pyproject.toml [project].dynamic must include "version".'

    # Rule B: the hatch source path is the one file we expect.
    hatch_version = pyproject.get("tool", {}).get("hatch", {}).get("version", {})
    assert hatch_version.get("path") == "clinosim/__init__.py", (
        f"[tool.hatch.version].path must be clinosim/__init__.py; got {hatch_version.get('path')!r}."
    )

    # Rule C: the actual __version__ string must be SemVer-shaped so tag
    # automation and PyPI don't reject it. Pre-release / build metadata OK.
    assert re.fullmatch(
        r"\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?",
        clinosim.__version__,
    ), f"clinosim.__version__={clinosim.__version__!r} is not SemVer-shaped."


@pytest.mark.unit
def test_console_entry_point_registered() -> None:
    """``clinosim`` console script must be discoverable from the installed
    package metadata. Skips when the checkout has not been installed
    (``pip install -e .`` never run), which happens for pure-source runs."""
    try:
        dist = metadata.distribution("clinosim")
    except metadata.PackageNotFoundError:
        pytest.skip("clinosim package not installed in this Python env")

    scripts = [ep for ep in dist.entry_points if ep.group == "console_scripts"]
    names = {ep.name: ep.value for ep in scripts}
    assert "clinosim" in names, f"console_scripts entry `clinosim` not registered; present: {sorted(names)}."
    assert names["clinosim"] == "clinosim.simulator.cli:main", (
        f"console_scripts entry `clinosim` points at {names['clinosim']!r}, expected clinosim.simulator.cli:main."
    )


@pytest.mark.unit
def test_cli_main_is_importable() -> None:
    """The entry point target must be importable independently of any
    installed shim (protects the package-source form for developers who
    do ``python -m clinosim.simulator.cli``-style invocation)."""
    from clinosim.simulator.cli import main  # noqa: F401 — import IS the test

    # Sanity: it's a callable, not a re-export of something odd.
    assert callable(main), "clinosim.simulator.cli.main must be callable."


@pytest.mark.unit
def test_python_version_gate() -> None:
    """We advertise ``requires-python = ">=3.11"``. If a test is running on
    something older, the packaging metadata is wrong."""
    assert sys.version_info >= (3, 11), f"clinosim requires Python 3.11+; running on {sys.version_info}."
