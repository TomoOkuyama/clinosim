"""FHIR R4 subpackage — resource builders, localization, and post-processing.

Issue #555 restructures the flat `clinosim/modules/output/` 41-file layout
into this subpackage, matching the convention used in other modules:
- `builders/`: one module per FHIR resource type
- `common.py`: shared FHIR helpers (promoted from `_fhir_common.py` in Issue #545)
- `localization.py`: locale-specific display mappings
- `reference_data.py`: canonical reference data (allergens, etc.)
- `inline_bb.py`: inline bundle builders (patient, encounter, medications, etc.)
- `post_process/`: post-emit normalization and profile application

The main entry point for external callers is `clinosim.modules.output.fhir_r4_adapter`,
which uses this subpackage's modules.
"""
