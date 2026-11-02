"""The one reader of clinosim data YAML (code-mapping spec §3.1, Issue #2465).

Every data file starts with a ``metadata`` block naming its ``kind``. The
block describes the file; it is not one of its sections, so
``load_data_yaml`` returns the content without it and ``data_metadata``
returns the block. The codes layer, the locale layer and module reference
data all read through these functions, so the header rule is applied the
same way everywhere. Callers keep their own caches.

This module imports nothing from clinosim, so every layer may use it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

__all__ = ["DATA_KINDS", "data_metadata", "load_data_yaml"]

# The kinds of data file (spec §3.2).
DATA_KINDS = frozenset(
    {
        "code-system",
        "map",
        "crosswalk",
        "catalog",
        "value-set",
        "country-mapping",
        "display-table",
        "translation-table",
        "phrase-catalog",
        "reference",
        "protocol",
    }
)


def _parse(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_data_yaml(path: Path) -> dict[str, Any]:
    """Content of the data YAML at ``path`` without its ``metadata`` header
    (``{}`` for an empty file); ``FileNotFoundError`` when it does not exist."""
    data = _parse(path) or {}
    if isinstance(data, dict) and "metadata" in data:
        return {k: v for k, v in data.items() if k != "metadata"}
    return data


def data_metadata(path: Path) -> dict[str, Any]:
    """The ``metadata`` header of the data YAML at ``path`` (``{}`` when absent)."""
    data = _parse(path) or {}
    meta = data.get("metadata") if isinstance(data, dict) else None
    return dict(meta) if isinstance(meta, dict) else {}
