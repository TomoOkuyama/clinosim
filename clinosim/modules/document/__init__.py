"""Document module (Tier 1 #3 α-min-1 always-on Module, AD-55 near-essential cascade).

統一 narrative generation interface + ClinicalImpression daily generation。

Public exports:
- DocumentTypeSpec / load_document_type_specs / specs_for_country / specs_for_encounter_type
- NarrativeContext / NarrativeOutput / DocumentType / FormatType (re-export from types)
- Canonical FHIR resource ID-prefix constants (writer-owned; readers import)
"""

from __future__ import annotations

from clinosim.modules.document.narrative.registry import (
    DocumentTypeSpec,
    load_document_type_specs,
    specs_for_country,
    specs_for_encounter_type,
)
from clinosim.modules.document.reference_data_loaders import (
    load_discharge_instructions,
    load_physical_exam_findings,
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

# AD-65 Bug B (Task 12): nursing-authored document LOINC codes, used by
# clinosim.modules.document.engine._pick_document_author to dispatch author
# to encounter.primary_nurse_id instead of encounter.attending_physician_id.
# Imported here (after the constants above are defined) rather than at the
# top of the module to avoid a circular import: engine.py imports the
# constants above FROM this package, so importing engine.py itself must
# happen only after those names already exist in this module's namespace.
from clinosim.modules.document.engine import NURSING_LOINCS  # noqa: E402

__all__ = [
    "DocumentType",
    "FormatType",
    "DocumentTypeSpec",
    "NarrativeContext",
    "NarrativeOutput",
    "load_document_type_specs",
    "specs_for_country",
    "specs_for_encounter_type",
    "load_physical_exam_findings",
    "load_discharge_instructions",
    "DOC_REFERENCE_ID_PREFIX",
    "COMPOSITION_ID_PREFIX",
    "ALLERGY_ID_PREFIX",
    "CLINICAL_IMPRESSION_ID_PREFIX",
    "NURSING_LOINCS",
]
