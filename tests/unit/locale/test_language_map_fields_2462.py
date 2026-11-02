"""Translatable fields in these tables are language maps, not
language-suffixed keys (code-mapping spec §3.1 rule 4, Issue #2462)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

import clinosim

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_FILES = (
    "codes/data/clinosim-clinician-role.yaml",
    "locale/shared/perinatal.yaml",
    "locale/shared/chronic_followup.yaml",
    "locale/shared/pregnancy_substitutions.yaml",
)
_SUFFIXED = re.compile(r"_(en|ja)$")


def _suffixed_keys(node: object, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and _SUFFIXED.search(key):
                found.append(f"{path}.{key}")
            found += _suffixed_keys(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found += _suffixed_keys(value, f"{path}[{i}]")
    return found


@pytest.mark.parametrize("rel", _FILES)
def test_no_language_suffixed_keys(rel: str) -> None:
    data = yaml.safe_load((_ROOT / rel).read_text(encoding="utf-8"))
    assert _suffixed_keys(data) == []
