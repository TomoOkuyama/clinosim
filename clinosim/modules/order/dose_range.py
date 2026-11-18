"""Resolve a protocol dose range to one dose (Issue #3265).

A disease protocol may write a dose as a range ("25-100mg PO daily", "15-20mg/kg
IV q12h", "NS 80-125 mL/h"); a prescription, an infusion order or an
administration record states one dose. :func:`resolve_dose_ranges` replaces
every dose range of a string by one end of it, by the rule of the range's unit
(``dose_range_resolution.yaml``: the starting, lower dose by default, the upper
rate for a maintenance-fluid rate). Deterministic; draws nothing.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from clinosim.datafiles import load_validated_yaml

__all__ = ["resolve_dose_ranges", "resolve_protocol_dose_ranges"]

_REF = Path(__file__).resolve().parent / "reference_data" / "dose_range_resolution.yaml"

_NUM = r"\d+(?:\.\d+)?"
_UNIT = r"(?:mcg|mg|ug|\u00b5g|mEq|mL|IU|units?|U|g|L)"
# "25-100mg", "15-20 mg/kg", "80-125 mL/h", "0.2-0.3 U/kg", "20-40 mEq/L".
_RANGE = re.compile(
    rf"(?<![\d.])(?P<lo>{_NUM})\s*-\s*(?P<hi>{_NUM})(?P<sep>\s*)(?P<unit>{_UNIT}(?:/(?:kg|m2|L)(?:/(?:h|hr|min))?|/(?:h|hr|min))?)(?![A-Za-z/])"
)
# A range after "target" or a comparison sign is a goal, not a dose.
_NOT_A_DOSE_BEFORE = re.compile(r"(?:target|uop|[<>\u2265\u2264])\s*$", re.IGNORECASE)


class _RuleFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_rule: Literal["start", "upper"]
    rules_by_unit: dict[str, Literal["start", "upper"]] = {}


@cache
def _rules() -> _RuleFile:
    return _RuleFile.model_validate(load_validated_yaml(_REF, _RuleFile))


def _end(unit: str, lo: str, hi: str) -> str:
    rule = _rules().rules_by_unit.get(unit, _rules().default_rule)
    return hi if rule == "upper" else lo


def resolve_dose_ranges(text: str) -> str:
    """``text`` with each dose range replaced by one dose of it."""
    if not text or "-" not in text:
        return text

    def _sub(m: re.Match[str]) -> str:
        if _NOT_A_DOSE_BEFORE.search(text[max(0, m.start() - 14) : m.start()]):
            return m.group(0)
        return f"{_end(m.group('unit'), m.group('lo'), m.group('hi'))}{m.group('sep')}{m.group('unit')}"

    return _RANGE.sub(_sub, text)


# Protocol keys whose string value is a dose, and the map of locale variants.
_DOSE_KEYS = ("dose", "detail")


def resolve_protocol_dose_ranges(node: Any) -> Any:
    """``node`` (a loaded protocol, in place) with the ``dose`` / ``detail`` of
    every entry resolved to one dose; the written range is kept on the entry
    as ``titration_range`` (Issue #3265)."""
    if isinstance(node, dict):
        for key in list(node):
            value = node[key]
            if key in _DOSE_KEYS and isinstance(value, str):
                resolved = resolve_dose_ranges(value)
                if resolved != value:
                    node[key] = resolved
                    node.setdefault("titration_range", value)
            elif key == "locale_detail" and isinstance(value, dict):
                for loc, detail in list(value.items()):
                    if isinstance(detail, str):
                        value[loc] = resolve_dose_ranges(detail)
            else:
                resolve_protocol_dose_ranges(value)
    elif isinstance(node, list):
        for item in node:
            resolve_protocol_dose_ranges(item)
    return node
