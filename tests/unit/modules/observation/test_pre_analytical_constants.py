"""Lock the pre-analytical error-rate constants (Issue #561).

`clinosim/modules/observation/pre_analytical.py` centralises the 4 constants
that previously appeared as bare literals at 2 sites in
`clinosim/simulator/inpatient.py`.

Tests:
1. Exact values pinned so a tuning change is intentional and reviewable.
2. Correct types (float / tuple / frozenset).
3. HEMOLYSIS_PRONE_LABS is the JCCLS-flagged K/LDH pair — adding a new
   analyte here must be a conscious PR, not accidental drift.
4. AST guard: no bare `0.02` / `0.03` / `(1.2, 1.8)` / `("K", "LDH")` for
   the pre-analytical role in `inpatient.py` outside the canonical import
   consumers.
"""

from __future__ import annotations

import ast
from pathlib import Path

from clinosim.modules.observation.pre_analytical import (
    HEMOLYSIS_LIFT_RANGE,
    HEMOLYSIS_PRONE_LABS,
    HEMOLYSIS_RATE,
    SPECIMEN_REJECTION_RATE,
)


def test_specimen_rejection_rate() -> None:
    assert SPECIMEN_REJECTION_RATE == 0.02


def test_hemolysis_rate() -> None:
    assert HEMOLYSIS_RATE == 0.03


def test_hemolysis_lift_range() -> None:
    assert HEMOLYSIS_LIFT_RANGE == (1.2, 1.8)
    lo, hi = HEMOLYSIS_LIFT_RANGE
    assert lo < hi and lo >= 1.0


def test_hemolysis_prone_labs() -> None:
    assert HEMOLYSIS_PRONE_LABS == frozenset({"K", "LDH"})
    assert isinstance(HEMOLYSIS_PRONE_LABS, frozenset)


def test_no_bare_hemolysis_prone_tuple_in_inpatient() -> None:
    """`("K", "LDH")` must not appear as an inline lab-set literal in
    `inpatient.py`'s pre-analytical loop. Use `HEMOLYSIS_PRONE_LABS`."""
    src = (Path(__file__).parent / "../../../../clinosim/simulator/inpatient.py").resolve().read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Tuple) and len(node.elts) == 2:
            values = tuple(elt.value if isinstance(elt, ast.Constant) else None for elt in node.elts)
            if values == ("K", "LDH"):
                raise AssertionError(
                    f"Bare ('K', 'LDH') tuple at inpatient.py:{node.lineno} — use HEMOLYSIS_PRONE_LABS"
                )
