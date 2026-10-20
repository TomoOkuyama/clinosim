"""Phase 4a Task 3 — drug-name → HomeMedication lookup.

Scans chronic_medications.yaml for the drug's full metadata; falls back
to a default HomeMedication on miss.
"""

from __future__ import annotations

from clinosim.modules.longitudinal.med_lookup import resolve_med_name


def test_resolve_known_drug_returns_full_metadata():
    """Metformin is defined under E11.9 in chronic_medications.yaml."""
    hm = resolve_med_name("Metformin")
    assert hm.drug_name == "Metformin"
    assert hm.route == "PO"
    assert hm.frequency == "bid"
    assert hm.dose == "500mg"


def test_resolve_unknown_drug_returns_default():
    """Review Focus #2: a drug not in chronic_medications.yaml falls
    back to a sensible default HomeMedication, not a crash."""
    hm = resolve_med_name("UnknownNewDrug__Phase4a_test")
    assert hm.drug_name == "UnknownNewDrug__Phase4a_test"
    assert hm.route == "PO"
    assert hm.frequency == "daily"
    assert hm.dose == ""


def test_resolve_is_cached():
    """Idempotent calls return equal HomeMedication instances."""
    hm1 = resolve_med_name("Metformin")
    hm2 = resolve_med_name("Metformin")
    assert hm1 == hm2


def test_resolve_empagliflozin_full_metadata():
    """Phase 4a Task 6: Empagliflozin added under E11.9 with probability: 0.0."""
    hm = resolve_med_name("Empagliflozin")
    assert hm.drug_name == "Empagliflozin"
    assert hm.route == "PO"
    assert hm.frequency == "daily"
    assert hm.dose == "10mg"


def test_resolve_insulin_glargine_full_metadata():
    hm = resolve_med_name("Insulin glargine")
    assert hm.drug_name == "Insulin glargine"
    assert hm.route == "SC"
    assert hm.frequency == "daily"
    assert hm.dose == "10U"


def test_resolve_hydrochlorothiazide_full_metadata():
    """Phase 4b.1 Task 6: HCTZ added under I10 with probability: 0.0."""
    hm = resolve_med_name("Hydrochlorothiazide")
    assert hm.drug_name == "Hydrochlorothiazide"
    assert hm.route == "PO"
    assert hm.frequency == "daily"
    assert hm.dose == "25mg"


def test_resolve_rosuvastatin_full_metadata():
    hm = resolve_med_name("Rosuvastatin")
    assert hm.drug_name == "Rosuvastatin"
    assert hm.route == "PO"
    assert hm.frequency == "daily"
    assert hm.dose == "20mg"


def test_resolve_ezetimibe_full_metadata():
    hm = resolve_med_name("Ezetimibe")
    assert hm.drug_name == "Ezetimibe"
    assert hm.route == "PO"
    assert hm.frequency == "daily"
    assert hm.dose == "10mg"
