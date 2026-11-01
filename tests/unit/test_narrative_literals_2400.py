"""Narrative output text comes from the phrase catalog; Japanese literals in
the narrative package are input-matching keys only (Issue #2400)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import clinosim

pytestmark = pytest.mark.unit

_JP = re.compile(r"[぀-ヿ一-鿿]")
_PKG = Path(clinosim.__file__).parent / "modules/document/narrative"

# Literals that match input text (they are never written to output).
_MATCH_KEYS = {
    "renderers/_composers.py": {"意識清明", "呼吸音清明"},
    "context.py": {"代謝異常", "フィトナジオン", "エリスロマイシン"},
    "renderers/section_builders/mortality.py": {"蘇生", "心肺蘇生"},
    "renderers/section_builders/op_pn_notes.py": {"アプローチ"},
    "_patient_info_renderers.py": {"就業中"},
    "semantic_check.py": {"改善後のセクション本文"},
}


def _literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # Docstrings and bare string statements (attribute docstrings) are documentation.
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and _JP.search(n.value)
    ]


def test_japanese_literals_are_match_keys_only() -> None:
    offenders = {}
    for path in _PKG.rglob("*.py"):
        rel = path.relative_to(_PKG).as_posix()
        extra = [lit for lit in _literals(path) if lit not in _MATCH_KEYS.get(rel, set())]
        if extra:
            offenders[rel] = extra
    assert not offenders, offenders
