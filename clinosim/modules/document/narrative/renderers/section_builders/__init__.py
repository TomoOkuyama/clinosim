"""Section-builder package — per-document-type section builders.

Each file carries one family (OPERATIVE_NOTE / PROCEDURE_NOTE /
DEATH_CERTIFICATE / care-plan / etc.) as free-standing functions
``(generator, ctx) -> (text, facts)``, each registered under its section
name with ``@section(...)`` (``_registry.py``, Issue #2531); the
composition renderer dispatches through that registry.
"""
