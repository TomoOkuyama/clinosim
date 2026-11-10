"""Format patterns as data — address lines and phone numbers (Issue #3141).

``docs/design-guides/country-profile-spec.md`` §2 ("formats as metadata",
libaddressinput / libphonenumber style): one formatter here, the per-country
templates in ``clinosim/locale/<cc>/addresses.yaml``. Code never selects a
format with a country branch.

A *pattern* is a mapping::

    fields:              # drawn in this order
      - {name: town, choice: towns}        # str(rng.choice(pools["towns"]))
      - {name: chome, integer: [1, 6]}     # int(rng.integers(1, 6))
    format: "{town}{chome}丁目"             # str.format over the drawn values
    then:                # optional: continue with the case a drawn value selects
      by: area
      cases:
        "03": {fields: [...], format: "..."}
        default: {fields: [...], format: "..."}

``choice`` names a list in ``pools`` (the locale data the pattern lives in).
The draws are exactly ``rng.choice`` / ``rng.integers`` in field order, so a
pattern reproduces the stream of the code it replaced. Field width / padding
is written in ``format`` (``{exchange:04d}``).

A *hash pattern* (:func:`format_hash_pattern`) formats a deterministic integer
instead of drawing: ``{"format": "03-{high:04d}-{low:04d}", "low_modulus":
10000, "high_modulus": 10000}`` gives ``low = h % low_modulus`` and
``high = (h // low_modulus) % high_modulus``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

__all__ = ["draw_pattern", "format_hash_pattern"]


def _draw_fields(
    fields: Sequence[Mapping[str, Any]],
    pools: Mapping[str, Any],
    rng: np.random.Generator,
    values: dict[str, Any],
) -> None:
    for field in fields:
        name = str(field["name"])
        if "choice" in field:
            values[name] = str(rng.choice(pools[str(field["choice"])]))
        elif "integer" in field:
            low, high = field["integer"]
            values[name] = int(rng.integers(int(low), int(high)))
        else:
            raise ValueError(f"pattern field {name!r} needs 'choice' or 'integer': {dict(field)}")


def draw_pattern(pattern: Mapping[str, Any], pools: Mapping[str, Any], rng: np.random.Generator) -> str:
    """Draw ``pattern``'s fields from ``rng`` and format them (module docstring)."""
    values: dict[str, Any] = {}
    current: Mapping[str, Any] = pattern
    while True:
        _draw_fields(current.get("fields") or (), pools, rng, values)
        then = current.get("then")
        if not then:
            return str(current["format"]).format(**values)
        cases = then["cases"]
        key = str(values[str(then["by"])])
        current = cases[key] if key in cases else cases["default"]


def format_hash_pattern(pattern: Mapping[str, Any], h: int) -> str:
    """Format the deterministic integer ``h`` with a hash pattern (module docstring)."""
    low_modulus = int(pattern["low_modulus"])
    low = h % low_modulus
    high = (h // low_modulus) % int(pattern["high_modulus"])
    return str(pattern["format"]).format(high=high, low=low)
