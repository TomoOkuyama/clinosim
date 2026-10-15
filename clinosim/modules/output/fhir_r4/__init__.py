"""FHIR R4 adapter — public facade.

The adapter logic (``convert_cif_to_fhir``, bundle builders, snapshot /
death reconciliation, scrubbers, etc.) lives in
:mod:`clinosim.modules.output.fhir_r4.builder`. This ``__init__`` is a
thin re-export layer so downstream callers keep writing

    from clinosim.modules.output.fhir_r4 import convert_cif_to_fhir

verbatim.

META #1633 P6 split: the former 1326-line ``__init__.py`` was promoted
to ``builder.py`` and this facade kept the public + the private
``_*`` symbols that tests + the ``fhir_r4_adapter`` shim reach into,
so no caller import changes.

See [`README.md`](README.md) for the FHIR resource → domain map.
"""

from __future__ import annotations

# Re-export the public surface. Explicit imports (not wildcard) so
# a rename in ``builder`` fails fast at import time and ``ruff``'s
# F405 star-import rule stays happy.
from clinosim.modules.output.fhir_r4.builder import (  # noqa: F401
    _AFTER_DEATH_ALLOWED_RESOURCE_TYPES,
    _AFTER_DEATH_START_GATED_RESOURCE_TYPES,
    _BUNDLE_BUILDERS,
    _POST_SNAPSHOT_ALLOWED_RESOURCE_TYPES,
    _build_bundle,
    _drop_entries_after_death,
    _drop_entries_after_snapshot,
    _fhir_id_is_spec_valid,
    available_builders,
    convert_cif_to_fhir,
    register_bundle_builder,
)

# Explicit ``__all__`` names every re-exported symbol so (a) mypy
# treats the ``_*`` names as deliberately exported (back-compat API
# for tests + the ``fhir_r4_adapter.py`` shim), and (b) a
# ``from fhir_r4 import *`` wildcard (performed by
# ``fhir_r4_adapter.py``) still sees both the public and private
# surfaces.
__all__ = [
    # Public API
    "available_builders",
    "convert_cif_to_fhir",
    "register_bundle_builder",
    # Back-compat private surface (tests + fhir_r4_adapter.py shim)
    "_AFTER_DEATH_ALLOWED_RESOURCE_TYPES",
    "_AFTER_DEATH_START_GATED_RESOURCE_TYPES",
    "_BUNDLE_BUILDERS",
    "_POST_SNAPSHOT_ALLOWED_RESOURCE_TYPES",
    "_build_bundle",
    "_drop_entries_after_death",
    "_drop_entries_after_snapshot",
    "_fhir_id_is_spec_valid",
]
