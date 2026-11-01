"""Code-system URIs and code-data tables are reached only through
``clinosim.codes`` (Issue #2266)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import clinosim
from clinosim.codes.loader import _BUILTIN_URIS

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_URIS = {uri for uri in _BUILTIN_URIS.values() if isinstance(uri, str)}


def _modules() -> list[tuple[str, ast.Module, str]]:
    out = []
    for path in sorted(_ROOT.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith("codes/"):
            continue
        source = path.read_text(encoding="utf-8")
        out.append((rel, ast.parse(source), source))
    return out


def test_no_code_system_uri_literal() -> None:
    hits = []
    for rel, tree, _ in _modules():
        docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        hits += [
            f"{rel}:{n.lineno} {n.value}"
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and n.value in _URIS
        ]
    assert not hits, "Use clinosim.codes.get_system_uri(<key>) (or the per-source accessor) instead:\n" + "\n".join(
        hits
    )


def test_no_private_registry_loader_import() -> None:
    hits = [
        f"{rel}:{n.lineno}"
        for rel, tree, _ in _modules()
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        and n.module == "clinosim.codes.loader"
        and any(alias.name == "_load_system" for alias in n.names)
    ]
    assert not hits, "Use clinosim.codes.display / lookup instead of _load_system:\n" + "\n".join(hits)


def test_no_direct_code_data_read() -> None:
    hits = []
    for rel, tree, _ in _modules():
        for n in ast.walk(tree):
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
                parts = [c.value for c in ast.walk(n) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
                if "codes" in parts and "data" in parts:
                    hits.append(f"{rel}:{n.lineno}")
            elif isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) in ("open", "Path"):
                if any(isinstance(a, ast.Constant) and "codes/data/" in str(a.value) for a in n.args):
                    hits.append(f"{rel}:{n.lineno}")
    assert not hits, "Read code-data tables through clinosim.codes.data_table(<name>):\n" + "\n".join(sorted(set(hits)))
