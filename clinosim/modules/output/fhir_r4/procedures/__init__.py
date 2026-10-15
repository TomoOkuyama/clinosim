"""FHIR R4 resource builders — procedures clinical domain (Issue #555 PR2).

Each module in this package produces FHIR fragments for one resource type
(or a tightly-scoped group). See `../README.md` for the FHIR resource →
domain mapping.

Namespace stub — the public surface for this clinical domain is each
sibling module's own exports (``from clinosim.modules.output.fhir_r4.
PACKAGE.MODULE import ...``). The empty ``__all__`` is intentional:
``from clinosim.modules.output.fhir_r4.PACKAGE import *`` does nothing.
"""

from __future__ import annotations

__all__: list[str] = []
