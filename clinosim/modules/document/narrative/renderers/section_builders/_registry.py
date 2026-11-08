"""Section-builder registry (Issue #2531).

Every section builder is a function ``(generator, ctx) -> (text, facts)``
registered under its section name with :func:`section`. The composition
renderer looks sections up here, so adding a section is one decorated
function.

A section that one document type writes differently from the others (the
ED note's assessment, Issue #2871) registers a builder for that document
type with ``@section(name, document_type=...)``; the renderer prefers it
over the shared builder of the same name.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Mapping
from functools import cache
from typing import Any

__all__ = [
    "SectionBuilder",
    "document_section_builders",
    "section",
    "section_builder",
    "section_builders",
]

SectionBuilder = Callable[[Any, Any], tuple[str, list[str]]]

_SECTIONS: dict[str, SectionBuilder] = {}
_DOCUMENT_SECTIONS: dict[tuple[str, str], SectionBuilder] = {}


def section(name: str, *, document_type: str | None = None) -> Callable[[SectionBuilder], SectionBuilder]:
    """Register the decorated function as the builder of section ``name``
    (of ``document_type`` only, when given)."""

    def register(fn: SectionBuilder) -> SectionBuilder:
        if document_type is None:
            if name in _SECTIONS and _SECTIONS[name] is not fn:
                raise ValueError(f"section {name!r} registered twice")
            _SECTIONS[name] = fn
            return fn
        key = (str(document_type), name)
        if key in _DOCUMENT_SECTIONS and _DOCUMENT_SECTIONS[key] is not fn:
            raise ValueError(f"section {name!r} of {document_type!r} registered twice")
        _DOCUMENT_SECTIONS[key] = fn
        return fn

    return register


@cache
def _import_builders() -> None:
    from clinosim.modules.document.narrative.renderers import section_builders as package

    for module in pkgutil.iter_modules(package.__path__):
        if not module.name.startswith("_"):
            importlib.import_module(f"{package.__name__}.{module.name}")


@cache
def section_builders() -> Mapping[str, SectionBuilder]:
    """All shared section builders; imports every builder module once."""
    _import_builders()
    return dict(_SECTIONS)


@cache
def document_section_builders() -> Mapping[tuple[str, str], SectionBuilder]:
    """The document-type builders, keyed ``(document_type, section)``."""
    _import_builders()
    return dict(_DOCUMENT_SECTIONS)


def section_builder(name: str) -> SectionBuilder:
    """The builder of section ``name`` (``KeyError`` when unknown)."""
    return section_builders()[name]
