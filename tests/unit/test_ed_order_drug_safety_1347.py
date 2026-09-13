"""Issue #1347 (META #1392 Cluster A part 4) — ED order path drug-safety gate.

Prior to this pass the ED order dispatcher (``simulator/emergency.py``)
only ran the demographic gate; it did NOT call
``check_candidate_against_active``. A random-sample review flagged a
patient on chronic Rivaroxaban + Celecoxib who received Ketorolac IV +
Ibuprofen PO in the same ED visit — 3-NSAID stacking on top of
anticoagulation.

This suite covers:
- New pair rule ``nsaid-stacking`` (any nsaid × nsaid → contraindicated)
- Existing ``anticoagulant-plus-nsaid`` still fires for NSAID vs
  Rivaroxaban/Warfarin/DOAC
"""

from __future__ import annotations

from clinosim.modules import drug_safety


def test_ketorolac_plus_ibuprofen_pair_fires_nsaid_stacking():
    v = drug_safety.check_pair("Ketorolac", "Ibuprofen")
    assert v.severity == "contraindicated"
    assert v.rule_id == "nsaid-stacking"


def test_celecoxib_plus_ibuprofen_pair_fires_nsaid_stacking():
    """Cross-selective + non-selective NSAID — both nsaid class, mutex fires."""
    v = drug_safety.check_pair("Celecoxib", "Ibuprofen")
    assert v.severity == "contraindicated"
    assert v.rule_id == "nsaid-stacking"


def test_aspirin_plus_ibuprofen_still_flags_nsaid_stacking():
    """Aspirin is dual-classed antiplatelet + nsaid. When paired with a
    non-Aspirin NSAID, either nsaid-stacking OR anticoagulant-plus-nsaid
    could theoretically fire. The engine picks the highest-severity rule
    — both are contraindicated, so any fire is acceptable."""
    v = drug_safety.check_pair("Aspirin", "Ibuprofen")
    assert v.severity == "contraindicated"


def test_rivaroxaban_plus_celecoxib_fires_anticoag_nsaid():
    """Regression: the pre-existing anticoagulant-plus-nsaid rule still
    catches DOAC + NSAID pairs; the new nsaid-stacking rule does not
    displace it."""
    v = drug_safety.check_pair("Rivaroxaban", "Celecoxib")
    assert v.severity == "contraindicated"
    assert v.rule_id == "anticoagulant-plus-nsaid"


def test_acetaminophen_plus_ibuprofen_allowed():
    """Sanity: Acetaminophen is not NSAID class — no stacking rule fires.
    Regression against overly-broad matching."""
    v = drug_safety.check_pair("Acetaminophen", "Ibuprofen")
    assert v.is_allowed


def test_diclofenac_plus_naproxen_fires_nsaid_stacking():
    """Both non-selective NSAIDs — mutex fires."""
    v = drug_safety.check_pair("Diclofenac", "Naproxen")
    assert v.severity == "contraindicated"
    assert v.rule_id == "nsaid-stacking"


def test_loxoprofen_plus_ibuprofen_fires_nsaid_stacking():
    """JP-specific NSAID (Loxoprofen) — mutex fires against Ibuprofen."""
    v = drug_safety.check_pair("Loxoprofen", "Ibuprofen")
    assert v.severity == "contraindicated"
    assert v.rule_id == "nsaid-stacking"
