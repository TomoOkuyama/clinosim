"""Per-document-type narrative renderers (hardcoded-review Phase B8).

Pilot package for the god-class split (CRITICAL C1): the 6539-line
``clinosim/modules/document/narrative/template_generator.py`` carries
the ``TemplateNarrativeGenerator`` class with 169 methods, including
~10 ``_render_<doc_type>_text`` renderers that could each live in their
own file. This package starts the migration one renderer at a time —
every renderer here is a free-standing module-level function that
receives ``(ctx, spec)`` and returns a ``NarrativeOutput``.

The ``TemplateNarrativeGenerator`` method of the same name becomes a
thin delegator so the per-renderer dispatch inside the class is
unchanged.
"""
