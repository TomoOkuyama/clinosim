"""``clinosim.types`` sits at the bottom of the dependency graph (Issue #2210)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_TYPES = Path(__file__).resolve().parents[2] / "clinosim" / "types"


def _module_imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
    return names


@pytest.mark.parametrize("path", sorted(_TYPES.glob("*.py")), ids=lambda p: p.name)
def test_types_import_no_module_package(path: Path) -> None:
    offending = [m for m in _module_imports(path) if m.startswith(("clinosim.modules", "clinosim.simulator"))]
    assert offending == [], f"{path.name} imports {offending}"


def test_moved_definitions_keep_their_old_import_paths() -> None:
    from clinosim.modules._shared import is_jp, is_us
    from clinosim.modules.drug_safety.verdict import SafetySkipEntry
    from clinosim.modules.longitudinal.snapshot import YearSnapshot
    from clinosim.types.drug_safety import SafetySkipEntry as TypesSkipEntry
    from clinosim.types.longitudinal import YearSnapshot as TypesYearSnapshot

    assert SafetySkipEntry is TypesSkipEntry and YearSnapshot is TypesYearSnapshot
    assert is_jp("jp") and is_us("US")
