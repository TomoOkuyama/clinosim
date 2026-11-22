"""Executing the actions a complication declares (Issue #3543).

A disease YAML lists ``actions`` on a complication. Only ``icu_transfer`` was
ever acted on, so an infectious complication (aspiration pneumonia, urinary
tract infection, surgical site infection, sepsis, ...) got no antibiotic. This
module resolves the antibiotic actions: the one canonical spelling of an
action, and the empirical regimen of a complication, taken from the first-line
antibiotics of the disease protocol that the reference data names for it.
Values live in ``reference_data/complication_actions.yaml``. Everything here is
RNG-free.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from clinosim.codes.drugs import drug_classes
from clinosim.datafiles import load_data_yaml

_Slug = StrictStr


class ComplicationActionRules(BaseModel):
    """Schema of ``reference_data/complication_actions.yaml`` (Issue #3543)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_hour: int = Field(ge=0, le=23)
    aliases: dict[_Slug, _Slug]
    antibiotic_actions: dict[_Slug, dict[_Slug, _Slug]] = Field(min_length=1)
    no_regimen: tuple[_Slug, ...]
    not_executed_antibiotic_actions: tuple[_Slug, ...]


@functools.cache
def complication_action_rules() -> ComplicationActionRules:
    """The validated complication-action rules."""
    return ComplicationActionRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "complication_actions.yaml")
    )


def canonical_action(action: str) -> str:
    """The canonical spelling of a complication action."""
    return complication_action_rules().aliases.get(action, action)


def antibiotic_actions_of(complication: dict[str, Any]) -> list[str]:
    """The canonical executed antibiotic actions a complication declares, in
    order and without repeats."""
    rules = complication_action_rules()
    out: dict[str, None] = {}
    for action in complication.get("actions", []) or []:
        if isinstance(action, str) and canonical_action(action) in rules.antibiotic_actions:
            out.setdefault(canonical_action(action))
    return list(out)


def regimen_protocol_id(action: str, complication_name: str) -> str | None:
    """The disease protocol whose first-line antibiotics are the empirical
    regimen of ``complication_name`` for ``action``, ``None`` when none is
    named."""
    return complication_action_rules().antibiotic_actions.get(action, {}).get(complication_name)


def first_line_antibiotics(first_line_block: Any, country_key: str) -> list[dict[str, Any]]:
    """The one empirical antibiotic of a ``drugs.first_line`` block for
    ``country_key``: its first entry of catalog class ``antibiotic`` that is
    ordered without a draw (no ``probability``). A block lists alternatives and
    add-on agents (a second first-line drug, an atypical-coverage drug) that
    a complication's empirical order does not repeat; ``[]`` when none."""
    if not isinstance(first_line_block, dict):
        return []
    entries = first_line_block.get(country_key, [])
    if isinstance(entries, dict):
        entries = [entries]
    for e in entries:
        if (
            isinstance(e, dict)
            and e.get("probability") is None
            and "antibiotic" in drug_classes(str(e.get("drug_id") or e.get("drug") or ""))
        ):
            return [e]
    return []
