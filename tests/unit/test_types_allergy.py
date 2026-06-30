"""Unit tests for clinosim.types.allergy(Tier 1 #3 α-min-1 PR1)."""

from __future__ import annotations

from datetime import date

from clinosim.types.allergy import Allergy, AllergyReaction


def test_allergy_reaction_defaults_no_op():
    r = AllergyReaction()
    assert r.manifestation_snomed == ""
    assert r.severity == "mild"


def test_allergy_defaults_no_op():
    a = Allergy()
    assert a.allergy_id == ""
    assert a.allergen_code == ""
    assert a.category == ""
    assert a.criticality == "low"
    assert a.verification_status == "confirmed"
    assert a.onset_date is None
    assert a.reactions == []


def test_allergy_full_payload():
    reaction = AllergyReaction(
        manifestation_snomed="247472004",
        manifestation_display="Rash",
        severity="moderate",
    )
    a = Allergy(
        allergy_id="al-pt1-1",
        allergen_code="387207008",
        allergen_display="Penicillin",
        category="medication",
        criticality="high",
        verification_status="confirmed",
        onset_date=date(2020, 6, 15),
        reactions=[reaction],
    )
    assert a.allergen_display == "Penicillin"
    assert a.reactions[0].severity == "moderate"
