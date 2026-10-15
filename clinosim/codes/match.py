"""Shared chronic-code / ICD-prefix matching helpers.

Multiple call sites across the simulator check whether a patient's
chronic-condition set contains any code starting with a given ICD-10
prefix (e.g. "E11" for Type 2 DM, "E78" for dyslipidemia, "I10" for
essential hypertension). Historically each caller re-expressed the
check inline, producing both duplication and drift (some callers
indexed by ``.code`` attribute on a ``ChronicCondition``, others
operated on a plain ``list[str]`` of codes, and a handful mixed the
two).

This module centralises the check so there is one canonical place
to tune (e.g. if the simulator ever adds category-header aliasing
or multi-code normalisation).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def has_icd_prefix(
    chronic_items: Iterable[Any] | None,
    prefixes: str | tuple[str, ...],
) -> bool:
    """Return True if any item in ``chronic_items`` has an ICD code
    starting with any of ``prefixes``.

    Accepts two shapes transparently:

    * Plain string codes (``list[str]`` / any iterable of ``str``) —
      the item is compared directly.
    * Objects with a ``.code`` attribute (e.g.
      ``ChronicCondition`` dataclass) — the attribute value is
      compared.

    An empty / ``None`` iterable returns ``False``. ``prefixes`` may
    be a single string or a tuple of strings (same semantics as
    ``str.startswith``'s second argument).
    """
    if not chronic_items:
        return False
    if isinstance(prefixes, str):
        prefixes = (prefixes,)
    for item in chronic_items:
        code = getattr(item, "code", item)
        if code and isinstance(code, str) and code.startswith(prefixes):
            return True
    return False
