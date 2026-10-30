"""Country-code predicates (Issue #2210).

The lowest layer of the package: no clinosim imports, so ``clinosim.types``
can use them without depending on ``clinosim.modules``. Re-exported by
``clinosim.modules._shared`` for existing callers.
"""

from __future__ import annotations

from functools import lru_cache

__all__ = ["is_jp", "is_us"]


@lru_cache(maxsize=16)
def is_jp(country: str) -> bool:
    """True when the country code refers to Japan (case-insensitive).

    Canonical JP-gating predicate (common-logic unification, 2026-07-02).
    Replaces the divergent inline idioms (``country == "JP"`` /
    ``country.lower() == "jp"`` / ``str(country).upper() == "JP"``) so every
    module gates on the same normalization.

    Perf (2026-10-17): ``lru_cache`` because this predicate is called
    ~56M times during a p=10000 5-year FHIR export, with ≤ 2 distinct
    inputs per export in practice. Cache size 16 covers all realistic
    input shapes (``"US"`` / ``"JP"`` / lower / mixed-case variants).
    """
    return str(country).strip().lower() == "jp"


@lru_cache(maxsize=16)
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
