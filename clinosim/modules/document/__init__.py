"""Document module (Tier 1 #3 α-min-1 always-on Module, AD-55 near-essential cascade).

統一 narrative generation interface + ClinicalImpression daily generation。

Public exports:
- DocumentTypeSpec / load_document_type_specs / specs_for_country
- NarrativeContext / NarrativeOutput / DocumentType / FormatType (re-export from types)
- Canonical FHIR resource ID-prefix constants (writer-owned; readers import)
"""

from __future__ import annotations

from clinosim.modules.document.narrative.registry import (
    DocumentTypeSpec,
    load_document_type_specs,
    specs_for_country,
)
from clinosim.types.document import (
    DocumentType,
    FormatType,
    NarrativeContext,
    NarrativeOutput,
)

# Canonical constants (writer-owned, readers import)
# DOC_REFERENCE_ID_PREFIX: FHIR DocumentReference.id = "doc-{encounter_id}-{seq}"
# COMPOSITION_ID_PREFIX:   FHIR Composition.id      = "comp-{encounter_id}-{seq}"
# ALLERGY_ID_PREFIX:       document module convention for referencing Allergy FHIR resources
#   NOTE: _fhir_patient.py uses "allergy-{patient_id}-{index:02d}" inline;
#   this constant canonicalises the prefix for Task 9 FHIR builders. (concern logged)
# CLINICAL_IMPRESSION_ID_PREFIX: FHIR ClinicalImpression.id = "ci-{encounter_id}-{day}"
DOC_REFERENCE_ID_PREFIX = "doc-"
COMPOSITION_ID_PREFIX = "comp-"
ALLERGY_ID_PREFIX = "allergy-"
CLINICAL_IMPRESSION_ID_PREFIX = "ci-"

__all__ = [
    "DocumentType",
    "FormatType",
    "DocumentTypeSpec",
    "NarrativeContext",
    "NarrativeOutput",
    "load_document_type_specs",
    "specs_for_country",
    "DOC_REFERENCE_ID_PREFIX",
    "COMPOSITION_ID_PREFIX",
    "ALLERGY_ID_PREFIX",
    "CLINICAL_IMPRESSION_ID_PREFIX",
]
