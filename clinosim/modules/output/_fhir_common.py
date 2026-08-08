"""Backwards-compatibility shim for _fhir_common (Issue #555).

_fhir_common.py was previously renamed to fhir_common.py in Issue #545 (public
promotion), then moved to fhir_r4/common.py in Issue #555 (subpackage
restructure).

This shim maintains backwards compatibility for any remaining direct imports
from the old path.
"""

# Re-export everything from the new location
from clinosim.modules.output.fhir_r4.common import *  # noqa: F401, F403
