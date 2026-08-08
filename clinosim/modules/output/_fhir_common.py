"""Deprecated compatibility shim (Issue #545).

`_fhir_common` was promoted to `fhir_common` because 69 external importers
across `clinosim/` and `tests/` already treated it as public. This module
remains for one release cycle to keep pre-migration imports working.

Migrate to::

    from clinosim.modules.output.fhir_common import ...

`from clinosim.modules.output._fhir_common import ...` continues to resolve
but emits ``DeprecationWarning`` on first import per Python interpreter
session.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "`clinosim.modules.output._fhir_common` is a deprecated compatibility "
    "shim; import from `clinosim.modules.output.fhir_common` instead. "
    "See Issue #545 for the migration guide.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export the entire public API so `from _fhir_common import X` keeps
# working for X in `fhir_common.__all__` AND for the underscore-prefixed
# helpers that are not part of `__all__` but that callers historically
# imported by name.
from clinosim.modules.output.fhir_common import *  # noqa: E402, F401, F403

# The `*` import only imports names listed in `__all__`. Re-import
# non-`__all__` helpers explicitly so `from _fhir_common import
# _parse_dose_for_mar` (etc) still resolves under the shim.
from clinosim.modules.output.fhir_common import (  # noqa: E402, F401
    _UCUM_CODE_MAP,
    _append_tz_if_missing,
    _coding_with_display,
    _escape_html,
    _parse_dose_for_mar,
    _sha1_b64,
    _social_category,
    _to_ucum_code,
    _validate_route_maps,
    _value,
)
