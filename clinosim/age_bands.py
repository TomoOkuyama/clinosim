"""Age-band keys of YAML tables (Issue #2516).

Data tables key age-dependent values by inclusive age bands: ``"18-49"``
covers ages 18 to 49 and ``"85+"`` covers 85 and older. These helpers are
the one parser and matcher for such keys; each caller states what a table
with no matching band yields.

Like ``clinosim.countries``, this module has no clinosim imports so any
layer can use it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TypeVar

__all__ = [
    "age_band_covers",
    "find_age_band",
    "lookup_age_band",
    "parse_age_band",
    "parse_closed_age_band",
]

_K = TypeVar("_K")
_V = TypeVar("_V")
_D = TypeVar("_D")


def parse_age_band(key: object) -> tuple[int, int | None]:
    """``"18-49"`` -> ``(18, 49)``; ``"85+"`` -> ``(85, None)``.

    Raises ``ValueError`` for any other shape.
    """
    raw = str(key).strip()
    if raw.endswith("+"):
        return int(raw[:-1]), None
    lo, hi = raw.split("-")
    return int(lo), int(hi)


def parse_closed_age_band(key: object) -> tuple[int, int]:
    """Like :func:`parse_age_band` for tables whose bands must be closed."""
    lo, hi = parse_age_band(key)
    if hi is None:
        raise ValueError(f"age band {key!r} must be closed ('lo-hi')")
    return lo, hi


def age_band_covers(key: object, age: int) -> bool:
    """Whether the band ``key`` covers ``age`` (``ValueError`` if malformed)."""
    lo, hi = parse_age_band(key)
    return lo <= age and (hi is None or age <= hi)


def find_age_band(keys: Iterable[_K], age: int, *, skip_malformed: bool = False) -> _K | None:
    """The first key whose band covers ``age``, or None.

    A malformed key raises ``ValueError`` unless ``skip_malformed`` is set.
    """
    for key in keys:
        try:
            covers = age_band_covers(key, age)
        except ValueError:
            if skip_malformed:
                continue
            raise
        if covers:
            return key
    return None


def lookup_age_band(
    table: Mapping[_K, _V] | None,
    age: int,
    default: _D,
    *,
    skip_malformed: bool = False,
) -> _V | _D:
    """The value of the first band in ``table`` covering ``age``, else ``default``."""
    if not table:
        return default
    key = find_age_band(table, age, skip_malformed=skip_malformed)
    return default if key is None else table[key]
