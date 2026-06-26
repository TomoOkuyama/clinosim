"""Shared utilities for AD-55 enricher modules.

Helpers used across multiple modules under ``clinosim/modules/<name>/enricher.py``
that would otherwise be duplicated. Add new cross-module helpers here when
DRY violations appear (and only then — premature centralization is worse than
local duplication).
"""
from __future__ import annotations

from typing import Any

import numpy as np


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


def normalize_probabilities(
    probs: list[float] | np.ndarray,
    fallback: str = "uniform",
) -> np.ndarray:
    """Normalize a non-negative weight vector to sum to 1.0.

    Args:
        probs: array or list of non-negative weights.
        fallback: "uniform" (default) returns equal weight on non-positive sum;
            "raise" raises ValueError instead.

    Returns:
        np.ndarray of dtype float64 summing to 1.0.

    Idempotency: if the input already sums to 1.0 (within float tolerance),
    the returned array is byte-identical to ``np.asarray(probs, dtype=float)``.
    This makes migration from no-op normalization to this helper byte-clean
    for any well-formed (hand-normalized) YAML weight data.

    Raises:
        ValueError: if any weight is negative, or if the input sums to zero and
            ``fallback="raise"``.
    """
    arr = np.asarray(probs, dtype=float)
    if (arr < 0).any():
        raise ValueError(
            f"normalize_probabilities: negative weight in {list(arr)}"
        )
    total = float(arr.sum())
    if total <= 0:
        if fallback == "uniform":
            n = max(len(arr), 1)
            return np.ones(n) / n
        raise ValueError(
            f"normalize_probabilities: non-positive sum in {list(arr)}"
        )
    return arr / total
