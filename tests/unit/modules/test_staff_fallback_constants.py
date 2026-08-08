"""Lock staff-ID fallback constants (Issue #562).

`clinosim/modules/staff/engine.py` exports 3 fallback sentinels used when
`assign_staff` finds an empty roster. Previously inlined as 10+ bare
"DR-001" / "NS-001" / "TECH-001" literals across the simulator; a
consistency drift (e.g. renaming DR-001 → PHYS-001 in one file but not
the others) was possible without a compile error.
"""

from __future__ import annotations

from clinosim.modules.staff.engine import (
    FALLBACK_NURSE_ID,
    FALLBACK_PHYSICIAN_ID,
    FALLBACK_TECH_ID,
)


def test_fallback_physician_id() -> None:
    assert FALLBACK_PHYSICIAN_ID == "DR-001"


def test_fallback_nurse_id() -> None:
    assert FALLBACK_NURSE_ID == "NS-001"


def test_fallback_tech_id() -> None:
    assert FALLBACK_TECH_ID == "TECH-001"


def test_no_bare_fallback_literals_in_simulator() -> None:
    """Guard against future inline drift — the 3 sentinels must NOT appear
    as bare literals anywhere under `clinosim/simulator/`. Test fixtures
    (under `tests/`) may legitimately reference the same strings and are
    NOT scanned."""
    from pathlib import Path

    sim_root = (Path(__file__).parent / "../../../clinosim/simulator").resolve()
    forbidden = {"DR-001", "NS-001", "TECH-001"}
    violations: list[str] = []
    for py in sim_root.rglob("*.py"):
        src = py.read_text()
        for lit in forbidden:
            if f'"{lit}"' in src:
                violations.append(f"{py.relative_to(sim_root.parent.parent)}: bare {lit!r}")
    assert not violations, f"Bare staff-ID fallback literals: {violations}. Use FALLBACK_* constants."
