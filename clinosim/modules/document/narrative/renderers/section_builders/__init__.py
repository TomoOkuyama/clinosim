"""Section-builder package — per-document-type section builders split
out of ``TemplateNarrativeGenerator`` into cohesive family modules.

Each file carries one family (OPERATIVE_NOTE / PROCEDURE_NOTE /
DEATH_CERTIFICATE / care-plan / etc.) as free-standing functions. The
class method of the same name stays as a thin delegator for backward
compatibility with ``renderers/composition_sections.py`` which still
looks up ``generator._build_<section>`` by name.

Hardcoded-review Phase C1d onward.
"""
