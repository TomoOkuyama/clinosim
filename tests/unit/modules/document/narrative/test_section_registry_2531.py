"""Section-builder registry (Issue #2531): every Composition section a
document spec lists has a registered builder, and every builder is used."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.document.narrative.renderers.section_builders._registry import section, section_builders
from clinosim.types.document import FormatType


def _spec_sections() -> set[str]:
    return {
        name
        for spec in load_document_type_specs().values()
        if spec.format_type == FormatType.COMPOSITION
        for country in ("US", "JP")
        for name in spec.composition_sections_for(country)
    }


def test_every_spec_section_has_a_builder() -> None:
    assert _spec_sections() <= set(section_builders())


def test_every_builder_is_used_by_a_spec() -> None:
    assert set(section_builders()) <= _spec_sections()


def test_a_section_cannot_be_registered_twice() -> None:
    with pytest.raises(ValueError, match="registered twice"):
        section("chief_complaint")(lambda generator, ctx: ("", []))
