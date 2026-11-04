"""Composition sections (ADMISSION_HP / DISCHARGE_SUMMARY / nursing /
ED / care-plan / op / procedure / etc.) narrative renderer.

Each section name in the spec is looked up in the section-builder registry
(``section_builders/_registry.py``, Issue #2531); an unregistered section gets
the generic fallback phrase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.renderers.section_builders._registry import section_builders
from clinosim.types.document import NarrativeContext, NarrativeOutput

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


def render_composition_sections(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext, spec: DocumentTypeSpec
) -> NarrativeOutput:
    """Build section dict per spec.composition_sections."""
    facts: list[str] = []
    sections: dict[str, str] = {}

    builders = section_builders()
    section_list = spec.composition_sections_for(ctx.locale.upper())
    for section in section_list:
        builder = builders.get(section)
        if builder is not None:
            text, section_facts = builder(generator, ctx)
            sections[section] = text
            facts.extend(section_facts)
        else:
            # Unknown section — generic fallback
            sections[section] = t("fallback.generic_fallback", ctx.target_lang)

    return NarrativeOutput(
        sections=sections,
        metadata={"generator": "template", "lang": ctx.target_lang},
        facts_used=facts,
    )
