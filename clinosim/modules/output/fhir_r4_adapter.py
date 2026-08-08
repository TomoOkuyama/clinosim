"""Backwards-compat shim for `fhir_r4_adapter` — Issue #555 PR1.

The FHIR R4 facade was promoted to :mod:`clinosim.modules.output.fhir_r4`
(the subpackage's ``__init__``). Callers may continue to import from
``fhir_r4_adapter`` for one release cycle; new code should use the
subpackage path directly.

Unlike the ``_fhir_common`` shim (Issue #545), this shim does NOT emit a
``DeprecationWarning`` because ``fhir_r4_adapter`` was never "deprecated"
— it is being promoted to a cleaner subpackage location as part of an
OSS-hygiene restructure.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4 import *  # noqa: E402, F401, F403

# Re-export private helpers historically imported from ``fhir_r4_adapter``
# by name — ``from ... import *`` only re-exports names in ``__all__``, so
# underscore-prefixed helpers need explicit re-import.
from clinosim.modules.output.fhir_r4 import (  # noqa: E402, F401
    _build_bundle,
    _BUNDLE_BUILDERS,
    _fhir_id_is_spec_valid,
)
