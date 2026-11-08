"""The LLM service engine holds no Japanese literal (Issue #2399; the
legacy template fallbacks were removed in Issue #2556)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import clinosim

pytestmark = pytest.mark.unit

_JP = re.compile(r"[぀-ヿ一-鿿]")


def test_no_japanese_literal_in_the_llm_engine() -> None:
    tree = ast.parse((Path(clinosim.__file__).parent / "modules/llm_service/engine.py").read_text(encoding="utf-8"))
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Module))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    hits = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings and _JP.search(n.value)
    ]
    assert not hits, hits
