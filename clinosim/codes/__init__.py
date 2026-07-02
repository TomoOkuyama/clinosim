"""Clinical code systems — international standards with multilingual display.

This module provides a unified lookup interface for clinical code systems:
- ICD-10-CM (US diagnoses)
- ICD-10 (WHO/JP diagnoses)
- LOINC (lab tests, vitals)
- SNOMED CT (clinical findings, procedures)
- RxNorm (US drugs)
- CPT (US procedures)
- JLAC10 (JP labs)
- YJ (JP drug codes)
- K-codes (JP procedures)

Design principle: CIF stores codes only (no display text). At output time
(FHIR, HL7v2, CSV, etc.), display text is resolved via this module in the
desired language.

Unlike locale/, this module is NOT locale-scoped. Code systems are
international standards; translations are one of the code's attributes.
"""

from clinosim.codes.loader import lookup, get_system_uri, get_display, system_key_for, CodeSystem

__all__ = ["lookup", "get_system_uri", "get_display", "system_key_for", "CodeSystem"]
