"""JP-CLINS composition builders (hardcoded-review Phase B2, C5a).

Per-profile Composition builders factored out of
``clinosim/modules/output/fhir_r4/documents/composition.py`` so each
JP-CLINS document type (eDischargeSummary, eReferral, eCheckup, …) owns
one file. The composition module's ``_bb_compositions`` dispatcher
imports the per-type builder entry points from this package.
"""
