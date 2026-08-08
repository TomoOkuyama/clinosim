"""Deprecated compatibility shim (Issue #545 → Issue #555).

`_fhir_common` was originally promoted to `fhir_common` because 69
external importers across `clinosim/` and `tests/` already treated it
as public (Issue #545). Issue #555 then moved it to
`clinosim.modules.output.fhir_r4.lib.common` as part of the FHIR
subpackage restructure.

This shim remains for one release cycle to keep pre-migration imports
working. Migrate to::

    from clinosim.modules.output.fhir_r4.lib.common import ...

`from clinosim.modules.output._fhir_common import ...` continues to
resolve but emits ``DeprecationWarning`` on first import per Python
interpreter session.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "`clinosim.modules.output._fhir_common` is a deprecated compatibility "
    "shim; import from `clinosim.modules.output.fhir_r4.lib.common` instead. "
    "See Issues #545 and #555 for the migration guide.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export the entire public API so `from _fhir_common import X` keeps
# working for X in `fhir_r4.lib.common.__all__` AND for the underscore-prefixed
# helpers that are not part of `__all__` but that callers historically
# imported by name.
from clinosim.modules.output.fhir_r4.lib.common import *  # noqa: E402, F401, F403

# The `*` import only imports names listed in `__all__`. Re-import
# non-`__all__` helpers explicitly so `from _fhir_common import
# _parse_dose_for_mar` (etc) still resolves under the shim.
# Issue #545 Step 3 backward-compat aliases — the 16 public helpers had a
# leading underscore before Step 3. External callers (or in-tree code that
# was not migrated by the mechanical rewrite) still importing via the
# underscore name resolve through these re-exports for one release cycle.
from clinosim.modules.output.fhir_r4.lib.common import (  # noqa: E402, F401
    _UCUM_CODE_MAP,
    _append_tz_if_missing,
    _build_address,
    _build_diagnosis_codeable_concept,
    _build_dosage_instruction,
    _build_reference_range,
    _build_telecom,
    _coding_with_display,
    _entry,
    _escape_html,
    _infer_severity,
    _loinc_coding,
    _make_participant,
    _map_diagnosis_code,
    _map_encounter_status,
    _map_mar_status,
    _micro_coding,
    _parse_dose_for_mar,
    _severity_coding,
    _sha1_b64,
    _social_category,
    _strip_protocol_prefix,
    _survey_category,
    _to_ucum_code,
    _validate_route_maps,
    _value,
)
