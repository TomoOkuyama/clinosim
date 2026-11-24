"""English ordinal suffixes (Issue #3701).

The single place that turns a number into its ordinal suffix, so every English
narrative phrase that prints an ordinal ("71st percentile") reuses one rule
instead of a fixed "th" in a template. The rule is
``locale/shared/ordinal_suffixes.yaml``.
"""

from __future__ import annotations

import functools
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml


class _OrdinalRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    default: str = Field(min_length=1)
    by_last_digit: dict[str, str]
    default_for_last_two_digits: list[str] = []


@functools.cache
def _rules() -> dict[str, _OrdinalRule]:
    raw = load_data_yaml(Path(__file__).resolve().parent / "shared" / "ordinal_suffixes.yaml")
    return {str(lang): _OrdinalRule.model_validate(rule) for lang, rule in raw.items()}


def ordinal_suffix(n: int, lang: str) -> str:
    """The suffix to append to ``n`` ("st", "nd", "rd", "th" in English).

    A language with no rule in the table returns ``""`` so a template shared
    across languages can carry ``{suffix}`` safely.
    """
    rule = _rules().get(lang)
    if rule is None:
        return ""
    digits = str(abs(int(n)))
    if digits[-2:] in rule.default_for_last_two_digits:
        return rule.default
    return rule.by_last_digit.get(digits[-1], rule.default)
