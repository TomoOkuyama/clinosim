"""AD-66 α-min-2c: narrative regression pytest suite configuration."""
from __future__ import annotations

from pathlib import Path


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "patient_profiles"


def profile_ids() -> list[str]:
    """Return sorted list of all profile ids (from *.yaml, excluding *.golden.json).

    Deterministic order (sorted) for parametrize stability.
    """
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.yaml"))
