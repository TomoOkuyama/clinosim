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

    Byte-clean migration property: for the typical pre-A3 pattern
    ``arr = np.asarray(probs, dtype=float); arr / arr.sum()`` (numpy
    float64 sum) this helper produces a byte-identical output, because
    ``float(np.float64)`` is bit-preserving for finite values, so the
    divisor bit pattern matches and the resulting float64 array matches.

    NOTE: this is NOT pure idempotency. An input that sums to ``0.9999...``
    in float64 (e.g. ``[0.27, 0.18, 0.16, 0.13, 0.10, 0.06, 0.10]``) is
    NOT returned unchanged; it is divided by ``0.9999...`` and gets a small
    perturbation (~1e-17 per element). The byte-clean property is symmetry
    with the pre-existing code, not identity on already-normalized arrays.

    Raises:
        ValueError: if the input is empty, if any weight is negative, or if the
            input sums to zero and ``fallback="raise"``.
    """
    arr = np.asarray(probs, dtype=float)
    if len(arr) == 0:
        raise ValueError(
            "normalize_probabilities: empty weight vector; cannot normalize"
        )
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
