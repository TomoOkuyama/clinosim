"""Shared FHIR helpers used by every domain-scoped builder (Issue #555).

- `common` — helpers previously at `output/fhir_common.py` (Issue #545 promotion).
- `localization` — locale-aware display resolution.
- `reference_data` — cross-resource lookup tables.
- `inline_bb` — inline bundle-builder helpers.
- `generator_metadata` — sim-params snapshot writer.
- `ids` — deterministic Resource.id derivation (Issue #349).
"""

from __future__ import annotations
