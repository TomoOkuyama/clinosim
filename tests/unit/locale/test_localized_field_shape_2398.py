"""Localized sibling fields use `<base>_<lang>` for every language present
(Issue #2398): a `<base>_ja` never sits beside an unsuffixed English `<base>`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import clinosim

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
# `dose` is the parseable dose string, not the English of `dose_ja` (the
# localized instructions are `dose_ja` / `dose_en`).
_NOT_LOCALIZED = {"dose"}


def _mixed(node: object, path: str) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key in node:
            if isinstance(key, str) and key.endswith("_ja"):
                base = key[:-3]
                if base in node and f"{base}_en" not in node and base not in _NOT_LOCALIZED:
                    found.append(f"{path}.{base}")
        for key, value in node.items():
            found += _mixed(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            found += _mixed(item, f"{path}[{i}]")
    return found


def test_no_unsuffixed_english_beside_japanese() -> None:
    hits = []
    for path in sorted(_ROOT.rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        hits += _mixed(data, path.relative_to(_ROOT).as_posix())
    assert not hits, hits
