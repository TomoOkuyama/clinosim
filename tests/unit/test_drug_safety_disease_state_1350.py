"""Issue #1350 (Cluster A of META #1392) — drug-vs-disease-state gate.

The ``check_candidate_against_disease_state`` engine function returns
verdicts when a candidate drug's ``drug_class`` overlaps a rule in
``disease_contraindications.yaml`` AND one of the patient's active
chronic-condition codes matches the rule's ``disease_predicate``. The
first three rules land the NSAID vs HF (I50) / cirrhosis (K74, K70.3) /
CKD stage 4-5 (N18.4/5/6) gates identified in Issue #1350 by random-
sample review.

Guardrails covered:
- NSAID (Celecoxib / Ibuprofen / Naproxen) + HF chronic → major
- NSAID + cirrhosis chronic → contraindicated
- NSAID + CKD stage 4/5 chronic → contraindicated
- Prefix match accepts base code ``I50`` and subcode ``I50.32``
- No trigger when the chronic condition doesn't match the predicate
- No trigger for non-NSAID drugs
- Activator ``_derive_home_medications`` drops the Celecoxib chronic
  MR for a patient sampled into M17 + HF chronic profile
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from clinosim.modules import drug_safety
from clinosim.modules.patient.activator import _derive_home_medications


@dataclass
class _Cond:
    code: str


def test_celecoxib_in_heart_failure_flags_major():
    verdicts = drug_safety.check_candidate_against_disease_state("Celecoxib", ["I50"])
    assert len(verdicts) == 1
    assert verdicts[0].severity == "major"
    assert verdicts[0].rule_id == "nsaid-in-heart-failure"


def test_ibuprofen_in_hf_with_subcode_flags_major():
    """Prefix match accepts subcodes like I50.32."""
    verdicts = drug_safety.check_candidate_against_disease_state("Ibuprofen", ["I50.32"])
    assert len(verdicts) == 1
    assert verdicts[0].severity == "major"


def test_naproxen_in_cirrhosis_flags_contraindicated():
    verdicts = drug_safety.check_candidate_against_disease_state("Naproxen", ["K74"])
    assert len(verdicts) == 1
    assert verdicts[0].severity == "contraindicated"
    assert verdicts[0].rule_id == "nsaid-in-cirrhosis"


def test_celecoxib_in_ckd_stage_4_flags_contraindicated():
    verdicts = drug_safety.check_candidate_against_disease_state("Celecoxib", ["N18.4"])
    assert len(verdicts) == 1
    assert verdicts[0].severity == "contraindicated"
    assert verdicts[0].rule_id == "nsaid-in-ckd-stage-4-5"


def test_celecoxib_in_ckd_stage_5_flags_contraindicated():
    verdicts = drug_safety.check_candidate_against_disease_state("Celecoxib", ["N18.5"])
    assert len(verdicts) == 1


def test_celecoxib_in_ckd_stage_3_no_trigger():
    """Rule targets stage 4-5 explicitly — stage 3 (N18.3) passes through."""
    verdicts = drug_safety.check_candidate_against_disease_state("Celecoxib", ["N18.3"])
    assert verdicts == []


def test_celecoxib_no_matching_condition_no_trigger():
    verdicts = drug_safety.check_candidate_against_disease_state("Celecoxib", ["E11.9", "I10"])
    assert verdicts == []


def test_non_nsaid_drug_no_trigger():
    """Acetaminophen is not NSAID class → no rule fires."""
    verdicts = drug_safety.check_candidate_against_disease_state("Acetaminophen", ["I50", "K74", "N18.4"])
    assert verdicts == []


def test_unknown_drug_no_trigger():
    """A drug not in the class registry returns empty (no classes to match)."""
    verdicts = drug_safety.check_candidate_against_disease_state("NonExistent", ["I50"])
    assert verdicts == []


def test_multiple_matching_conditions_returns_multiple_verdicts():
    """Patient with HF + cirrhosis on Celecoxib → 2 rules fire (both HF and cirrhosis)."""
    verdicts = drug_safety.check_candidate_against_disease_state("Celecoxib", ["I50", "K74"])
    assert len(verdicts) == 2
    rule_ids = {v.rule_id for v in verdicts}
    assert "nsaid-in-heart-failure" in rule_ids
    assert "nsaid-in-cirrhosis" in rule_ids


# --------------------------------------------------------------------------- #
# End-to-end via _derive_home_medications: Celecoxib is dropped when the
# patient carries a matching contraindicated chronic condition.


def test_derive_home_medications_drops_celecoxib_for_m17_plus_hf():
    """A patient with both M17 (osteoarthritis, where Celecoxib is a
    candidate at prob 0.3) and I50 (heart failure, chronic) must never
    receive Celecoxib as a chronic MR — the ``nsaid-in-heart-failure``
    rule fires and the activator drops the candidate."""
    hits_celecoxib = 0
    for i in range(200):
        meds = _derive_home_medications(
            [_Cond("M17"), _Cond("I50")],
            rng=np.random.default_rng(i),
            country="US",
        )
        if any("Celecoxib" in m.drug_name for m in meds):
            hits_celecoxib += 1
    assert hits_celecoxib == 0, f"Celecoxib emitted in {hits_celecoxib}/200 M17+I50 patients (must be 0)"


def test_derive_home_medications_still_emits_celecoxib_for_m17_only():
    """M17 alone (no HF / cirrhosis / CKD-4-5) → Celecoxib emits at
    roughly its yaml probability (0.3). Sanity-check that the gate
    only fires on the joint condition, not the standalone M17 path."""
    hits_celecoxib = 0
    for i in range(200):
        meds = _derive_home_medications(
            [_Cond("M17")],
            rng=np.random.default_rng(i),
            country="US",
        )
        if any("Celecoxib" in m.drug_name for m in meds):
            hits_celecoxib += 1
    # Expected around 60 (0.3 × 200), tolerance ±25%.
    assert 40 <= hits_celecoxib <= 80, f"Celecoxib emitted in {hits_celecoxib}/200 M17-only patients (expected ~60)"
