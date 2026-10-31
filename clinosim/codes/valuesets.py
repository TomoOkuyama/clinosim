"""Shared value sets (code groups) for decision logic (Issue #2280).

Decision logic asks questions such as "does this patient have dementia?" by
testing ICD codes. The code groups live in ``clinosim/codes/data/valuesets.yaml``;
this module reads them and offers one normalisation and one membership test,
so modules stop writing their own code lists and ``startswith`` / substring
checks.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml

__all__ = [
    "ValueSet",
    "concept_group",
    "group_names",
    "has_condition",
    "has_icd_prefix",
    "icd_base",
    "iter_chronic_codes",
    "normalize_icd",
]

_DATA_FILE = Path(__file__).parent / "data" / "valuesets.yaml"


def normalize_icd(code: str) -> str:
    """Trim and upper-case an ICD code, keeping the dot."""
    return str(code or "").strip().upper()


def icd_base(code: str) -> str:
    """The ICD-10 category (the part before the dot) of a code."""
    return normalize_icd(code).split(".")[0]


@dataclass(frozen=True)
class ValueSet:
    """A named code group."""

    name: str
    space: Literal["internal", "emitted"]
    match: Literal["prefix", "exact"]
    members: tuple[str, ...]

    def contains(self, code: str) -> bool:
        c = normalize_icd(code)
        if not c:
            return False
        if self.match == "exact":
            return c in self.members
        return c.startswith(self.members)


@cache
def _load() -> dict[str, ValueSet]:
    raw = yaml.safe_load(_DATA_FILE.read_text(encoding="utf-8")) or {}
    out: dict[str, ValueSet] = {}
    for name, body in (raw.get("groups") or {}).items():
        space = body.get("space")
        match = body.get("match")
        if space not in ("internal", "emitted") or match not in ("prefix", "exact"):
            raise ValueError(f"valuesets.yaml: group {name!r} needs space internal|emitted and match prefix|exact")
        out[str(name)] = ValueSet(
            name=str(name),
            space=space,
            match=match,
            members=tuple(normalize_icd(m) for m in body.get("members") or []),
        )
    return out


def group_names() -> frozenset[str]:
    """Every defined group name."""
    return frozenset(_load())


def patient_condition_names() -> frozenset[str]:
    """Names usable as a patient condition in disease YAMLs (severity modifiers
    and complication risk factors): every ``space: internal`` group (Issue #2285).

    Both evaluators resolve these names through :func:`has_condition`, so a
    name means the same thing wherever it appears.
    """
    return frozenset(name for name, vs in _load().items() if vs.space == "internal")


def concept_group(name: str) -> ValueSet:
    """The value set called ``name``; ``KeyError`` when it is not defined."""
    try:
        return _load()[name]
    except KeyError:
        raise KeyError(f"valuesets.yaml: no group {name!r}") from None


def iter_chronic_codes(items: Iterable[Any] | None) -> list[str]:
    """Plain codes from chronic-condition items of any shape.

    Accepts code strings, objects with a ``.code`` attribute
    (``ChronicCondition``) and dicts with a ``"code"`` key; empty items are
    skipped.
    """
    codes: list[str] = []
    for item in items or []:
        if isinstance(item, str):
            code = item
        elif isinstance(item, dict):
            code = item.get("code") or ""
        else:
            code = getattr(item, "code", "") or ""
        if code:
            codes.append(str(code))
    return codes


def has_condition(person_or_patient: Any, group: str) -> bool:
    """True when any chronic condition of the person / patient is in ``group``."""
    vs = concept_group(group)
    items = getattr(person_or_patient, "chronic_conditions", None)
    return any(vs.contains(c) for c in iter_chronic_codes(items))


def has_icd_prefix(chronic_items: Iterable[Any] | None, prefixes: str | tuple[str, ...]) -> bool:
    """True when any chronic-condition item's code starts with any of ``prefixes``.

    Former ``clinosim.codes.match.has_icd_prefix`` (re-exported there);
    prefer :func:`has_condition` with a named group for new code.
    """
    if isinstance(prefixes, str):
        prefixes = (prefixes,)
    return any(code.startswith(prefixes) for code in iter_chronic_codes(chronic_items))
