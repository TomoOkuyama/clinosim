"""AD-66 α-min-2c: narrative regression pytest suite configuration."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "patient_profiles"

_HERE = Path(__file__).resolve().parent

_OPT_IN_SKIP = pytest.mark.skip(
    reason="regression suite is opt-in: run with -m regression "
    "(subprocess latency + β-JP-1 LLM cost budget)"
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Make the regression suite genuinely opt-in (adv-1 F-3).

    A plain `pytest` run (or a directory-targeted `pytest tests/regression`)
    collects these tests; without this hook they would EXECUTE despite the
    documented opt-in contract. Skip every item in this directory unless the
    run's -m expression selects the regression marker.
    """
    markexpr = config.getoption("-m", default="") or ""
    if "regression" in markexpr:
        return
    for item in items:
        if _HERE in Path(str(item.path)).resolve().parents:
            item.add_marker(_OPT_IN_SKIP)


def profile_ids() -> list[str]:
    """Return sorted list of all profile ids (from *.yaml, excluding *.golden.json).

    Deterministic order (sorted) for parametrize stability.
    """
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.yaml"))
