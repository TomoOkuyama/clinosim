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
