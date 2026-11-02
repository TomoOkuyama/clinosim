"""Loader for module reference data (code-mapping spec §3.2, Issue #2466).

Reference data — thresholds, keyword lists, content that is not code or
display data — lives with the module that owns the rule, in
``<package>/reference_data/<name>.yaml``. ``clinosim/codes/data`` holds only
code systems, maps, crosswalks, catalogs and value sets.
"""

from __future__ import annotations

import copy
from functools import cache
from pathlib import Path
from typing import Any

from clinosim.datafiles import load_data_yaml

__all__ = ["load_reference_yaml"]


@cache
def _parsed(path: Path) -> dict[str, Any]:
    return load_data_yaml(path)


def load_reference_yaml(path: Path) -> dict[str, Any]:
    """Parsed reference-data YAML at ``path`` (a copy, so callers may reshape
    it); ``FileNotFoundError`` when it does not exist."""
    return copy.deepcopy(_parsed(path))
