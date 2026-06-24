"""Shared utilities for AD-55 enricher modules.

Helpers used across multiple modules under ``clinosim/modules/<name>/enricher.py``
that would otherwise be duplicated. Add new cross-module helpers here when
DRY violations appear (and only then — premature centralization is worse than
local duplication).
"""
from __future__ import annotations

from typing import Any


def get_attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from ``obj`` whether ``obj`` is a dict or has attributes.

    Used by enrichers that consume ``ctx`` / ``ctx.config`` / record objects
    that may arrive as either dataclass instances or dicts depending on
    upstream loaders. Returns ``default`` if the attribute / key is missing
    or if ``obj`` is ``None``.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
