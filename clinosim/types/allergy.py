"""Allergy CIF dataclasses.

Stored on ``PatientProfile.allergies``. The FHIR
``AllergyIntolerance`` mapping lives in
``clinosim/modules/output/fhir_r4/conditions/allergy.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class AllergyReaction:
    """Allergic reaction manifestation."""

    manifestation_snomed: str = ""  # SNOMED CT code
    severity: str = "mild"  # mild / moderate / severe


@dataclass
class Allergy:
    """Patient allergy/intolerance(AD-30 code-only CIF)."""

    allergy_id: str = ""  # patient-internal id
    allergen_code: str = ""  # SNOMED for allergen substance
    category: str = ""  # "medication" / "food" / "environment"
    criticality: str = "low"  # low / high / unable-to-assess
    verification_status: str = "confirmed"  # confirmed / unconfirmed / refuted
    # C1-17 (cycle 1): clinicalStatus per FHIR R4 AllergyIntolerance.
    # active (currently reactive) / inactive / resolved (childhood outgrown).
    clinical_status: str = "active"
    onset_date: date | None = None
    reactions: list[AllergyReaction] = field(default_factory=list)
