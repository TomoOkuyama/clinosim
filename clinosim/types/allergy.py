"""Allergy CIF dataclasses(Tier 1 #3 α-min-1 PR1).

PatientProfile.allergies に格納、FHIR AllergyIntolerance への mapping は
clinosim/modules/output/_fhir_allergy_intolerance.py で。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class AllergyReaction:
    """Allergic reaction manifestation."""

    manifestation_snomed: str = ""    # SNOMED CT code
    severity: str = "mild"            # mild / moderate / severe


@dataclass
class Allergy:
    """Patient allergy/intolerance(AD-30 code-only CIF)."""

    allergy_id: str = ""              # patient-internal id
    allergen_code: str = ""           # SNOMED for allergen substance
    category: str = ""                # "medication" / "food" / "environment"
    criticality: str = "low"          # low / high / unable-to-assess
    verification_status: str = "confirmed"  # confirmed / unconfirmed / refuted
    onset_date: date | None = None
    reactions: list[AllergyReaction] = field(default_factory=list)
