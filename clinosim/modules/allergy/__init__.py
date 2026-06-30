"""Allergy module (Tier 1 #3 α-min-1 always-on Module, AD-55 Base).

Patient allergy sampling、PatientProfile.allergies に populate。
POST_POPULATION enricher、age/sex-driven prevalence sampling。
"""

from __future__ import annotations

from clinosim.types.allergy import Allergy, AllergyReaction

__all__ = ["Allergy", "AllergyReaction"]
