"""FHIR R4 resource builders — extracted from flat output/ module (Issue #555).

One builder module per FHIR resource type, restructured from `_fhir_*.py` flat
layout into subpackage for clarity and maintainability.

Public API: imported by external callers via `clinosim.modules.output.fhir_r4`
or via submodule imports.
"""
