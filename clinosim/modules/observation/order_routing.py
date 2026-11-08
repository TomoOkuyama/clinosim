"""What a protocol lab-list entry orders (Issue #2583).

Disease and encounter YAML list everything a clinician asks for at a step
under ``labs`` / ``add_labs``. Most entries are one lab test (resolved through
``lab_aliases.yaml``); ``reference_data/order_routing.yaml`` routes the rest:
a vital sign or a history item is not ordered, an imaging study is ordered as imaging, and a
named group is ordered as its component labs.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from clinosim.datafiles import load_validated_yaml
from clinosim.types.encounter import OrderType

_REF_DIR = Path(__file__).resolve().parent / "reference_data"


@dataclass(frozen=True)
class OrderTarget:
    """One order a lab-list entry places."""

    name: str
    order_type: OrderType


class OrderRouting(BaseModel):
    """Shape of order_routing.yaml: each routed name appears in one section,
    and every expansion component is a lab with a US code."""

    model_config = ConfigDict(extra="forbid")

    vital_signs: list[str]
    history: list[str]
    imaging: dict[str, str]
    expansions: dict[str, list[str]]

    @model_validator(mode="after")
    def _routes_are_unambiguous_and_coded(self) -> OrderRouting:
        from clinosim.locale.loader import load_code_mapping
        from clinosim.modules.observation.engine import canonical_lab_name

        sections = [set(self.vital_signs), set(self.history), set(self.imaging), set(self.expansions)]
        seen: set[str] = set()
        for names in sections:
            if names & seen:
                raise ValueError(f"order_routing.yaml: {sorted(names & seen)} routed in more than one section")
            seen |= names
        us = load_code_mapping("lab", "US")
        for group, components in self.expansions.items():
            if not components:
                raise ValueError(f"order_routing.yaml: expansion {group!r} has no components")
            uncoded = [c for c in components if canonical_lab_name(c) not in us]
            if uncoded:
                raise ValueError(f"order_routing.yaml: expansion {group!r} components {uncoded} have no US lab code")
        return self


@lru_cache(maxsize=1)
def _routing() -> dict[str, Any]:
    return load_validated_yaml(_REF_DIR / "order_routing.yaml", OrderRouting)


def lab_order_targets(name: str) -> tuple[OrderTarget, ...]:
    """The orders a protocol lab-list entry ``name`` places, in order: none for
    a vital sign or a history item, one imaging order for an imaging study, the component labs
    of a named group, else ``name`` itself as one lab order."""
    routing = _routing()
    if name in routing["vital_signs"] or name in routing["history"]:
        return ()
    if name in routing["imaging"]:
        return (OrderTarget(routing["imaging"][name], OrderType.IMAGING),)
    components = routing["expansions"].get(name)
    if components:
        return tuple(OrderTarget(c, OrderType.LAB) for c in components)
    return (OrderTarget(name, OrderType.LAB),)
