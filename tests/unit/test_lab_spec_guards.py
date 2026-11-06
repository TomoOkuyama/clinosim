"""Guards of docs/design-guides/lab-orders-and-results-spec.md (Issue #2728):
true lab values are derived only through ``patient_true_labs``."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PKG = Path(__file__).resolve().parents[2] / "clinosim"
# The shared function itself, and the physiology engine that defines it.
_ALLOWED = {"simulator/lab_pipeline.py", "modules/physiology/engine.py"}


def test_true_lab_values_only_through_patient_true_labs() -> None:
    offenders = [
        f"{p.relative_to(_PKG)}:{i}"
        for p in sorted(_PKG.rglob("*.py"))
        if str(p.relative_to(_PKG)) not in _ALLOWED
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\bderive_lab_values\(", line) and not line.lstrip().startswith("#")
    ]
    assert not offenders, offenders
