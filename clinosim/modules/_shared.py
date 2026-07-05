"""Shared utilities for AD-55 enricher modules.

Helpers used across multiple modules under ``clinosim/modules/<name>/enricher.py``
that would otherwise be duplicated. Add new cross-module helpers here when
DRY violations appear (and only then — premature centralization is worse than
local duplication).
"""
from __future__ import annotations

from typing import Any

import numpy as np


def is_jp(country: str) -> bool:
    """True when the country code refers to Japan (case-insensitive).

    Canonical JP-gating predicate (common-logic unification, 2026-07-02).
    Replaces the divergent inline idioms (``country == "JP"`` /
    ``country.lower() == "jp"`` / ``str(country).upper() == "JP"``) so every
    module gates on the same normalization.
    """
    return str(country).strip().lower() == "jp"


def is_us(country: str) -> bool:
    """True when the country code refers to the United States (case-insensitive).

    Sibling to ``is_jp``. Locale loaders with only US/JP data files use
    ``is_us(country) or is_jp(country)`` to gate on "supported country" and
    return ``{}`` otherwise, rather than silently falling back to US data
    for an unrecognized country (locale-loader unsupported-country contract,
    2026-07-02 grand design review; ``care_level.load_rates`` is the
    original compliant precedent this generalizes).
    """
    return str(country).strip().lower() == "us"


def resolve_lang(country: str) -> str:
    """Display language for a country: ``"ja"`` for JP, ``"en"`` otherwise.

    Single edit point for the ``lang = "ja" if <country is JP> else "en"``
    selection previously inlined at each FHIR builder / enricher call site.
    """
    return "ja" if is_jp(country) else "en"


def strip_protocol_prefix(name: str) -> tuple[str, str]:
    """Strip protocol/category prefix from drug order text (AD-50).

    "DVT_prophylaxis: Enoxaparin 2000IU SC daily"
        → ("Enoxaparin 2000IU SC daily", "DVT prophylaxis")
    "antipyretic: Acetaminophen 500mg PO q6h PRN temp >= 38.5"
        → ("Acetaminophen 500mg PO q6h PRN temp >= 38.5", "antipyretic")
    "Ceftriaxone 1g IV q8h" → ("Ceftriaxone 1g IV q8h", "")

    Returns (cleaned_name, protocol_category).

    Promoted from ``modules/output/_fhir_common.py`` (β-JP-1 chain 1a adv-1
    I-1): narrative rendering (``modules/document``) needs the same
    normalization as the FHIR medication builders — single edit point per the
    data-logic unification rule. ``_fhir_common._strip_protocol_prefix`` is an
    alias of this function.
    """
    if ":" in name:
        prefix, rest = name.split(":", 1)
        rest = rest.strip()
        if rest:
            return rest, prefix.replace("_", " ").strip()
    return name, ""


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

    Conventions (PR-A / Fix #100 / PR #102 2026-06-27 確立):

    - **YAML-sourced callsites MUST use ``fallback="raise"``** so a YAML edit
      accident (e.g. all weights set to 0) is caught loudly at runtime instead
      of silently defaulting to uniform sampling (= PR-90 class silent-no-op).
      All 15 YAML-sourced callsites have been migrated as of 2026-06-27
      (PR #102 added 10 callsites in hai / population / clinical_course;
      pre-PR migration covered 5 in code_status / family_history / care_level
      / observation/microbiology via PR-A Fix #100/#101).
    - **Inline literal weight callsites MAY use ``fallback="uniform"``** (the
      default), since literal weight lists cannot zero out via YAML editing.
    - Upstream validators (``_validate_microbiology``,
      ``_validate_hai_organisms``, ``_validate_demographics``,
      ``_validate_names``, ``_validate_addresses``) catch zero-sum at import
      time as an additional layer of defense (silent-no-op defense triplet:
      canonical constants + upstream validate + backward raise).

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
