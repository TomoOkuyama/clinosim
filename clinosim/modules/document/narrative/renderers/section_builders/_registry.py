"""Section-builder registry (Issue #2531).

Every section builder is a function ``(generator, ctx) -> (text, facts)``
registered under its section name with :func:`section`. The composition
renderer looks sections up here, so adding a section is one decorated
function.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Mapping
from functools import cache
from typing import Any

__all__ = ["SectionBuilder", "section", "section_builder", "section_builders"]

SectionBuilder = Callable[[Any, Any], tuple[str, list[str]]]

_SECTIONS: dict[str, SectionBuilder] = {}


def section(name: str) -> Callable[[SectionBuilder], SectionBuilder]:
    """Register the decorated function as the builder of section ``name``."""

    def register(fn: SectionBuilder) -> SectionBuilder:
        if name in _SECTIONS and _SECTIONS[name] is not fn:
            raise ValueError(f"section {name!r} registered twice")
        _SECTIONS[name] = fn
        return fn

    return register


@cache
def section_builders() -> Mapping[str, SectionBuilder]:
    """All registered sections; imports every builder module once."""
    from clinosim.modules.document.narrative.renderers import section_builders as package

    for module in pkgutil.iter_modules(package.__path__):
        if not module.name.startswith("_"):
            importlib.import_module(f"{package.__name__}.{module.name}")
    return dict(_SECTIONS)


def section_builder(name: str) -> SectionBuilder:
    """The builder of section ``name`` (``KeyError`` when unknown)."""
    return section_builders()[name]
