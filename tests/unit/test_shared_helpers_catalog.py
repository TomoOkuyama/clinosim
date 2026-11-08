"""Every helper named in the shared-helpers catalog exists where the catalog says.

The catalog (``docs/design-guides/shared-helpers-catalog.md``) is the lookup
table contributors use instead of re-implementing a helper; a row that points
at a renamed or moved symbol sends them back to writing a copy.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_CATALOGS = (
    _ROOT / "docs/design-guides/shared-helpers-catalog.md",
    _ROOT / "docs/design-guides/shared-helpers-catalog.ja.md",
)
_TOKEN = re.compile(r"`([^`]+)`")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _module_name(token: str) -> str | None:
    if token.endswith(".py"):
        return token[: -len(".py")].replace("/", ".")
    if token.startswith("clinosim/") and "." not in token:
        return token.replace("/", ".")
    return None


def _catalog_refs(path: Path) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `clinosim"):
            continue
        first_cell = line.split("|")[1]
        module: str | None = None
        for token in _TOKEN.findall(first_cell):
            name = _module_name(token)
            if name is not None:
                module = name
                continue
            match = _IDENT.match(token)
            if module is not None and match is not None:
                refs.append((module, match.group(0)))
    return refs


@pytest.mark.parametrize("catalog", _CATALOGS, ids=lambda p: p.name)
def test_catalog_symbols_resolve(catalog: Path) -> None:
    refs = _catalog_refs(catalog)
    assert len(refs) > 100, f"{catalog.name}: parsed only {len(refs)} helper references"
    missing = [f"{module}.{symbol}" for module, symbol in refs if not hasattr(importlib.import_module(module), symbol)]
    assert not missing, f"{catalog.name} names helpers that do not exist: {missing}"


def test_catalog_languages_list_the_same_helpers() -> None:
    en, ja = (_catalog_refs(p) for p in _CATALOGS)
    assert en == ja
