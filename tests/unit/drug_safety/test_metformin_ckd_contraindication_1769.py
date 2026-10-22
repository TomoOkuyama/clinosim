"""Issue #1769 — Metformin must not be added to home medications when the
patient's chronic N18 (CKD) is staged G3b, G4, or G5. FDA label:
contraindicated at eGFR < 30 (CKD stage 4-5). KDIGO 2024: caution /
dose-reduce at G3b, discontinue at G4-G5.

This scope covers INITIAL activation only (home-med derivation at
patient activation time). Mid-sim CKD progression -> med_removal event
is tracked separately under Cluster B (#1752 / longitudinal engine
refactor) and is out of scope for this PR.
"""

from __future__ import annotations

import pytest

from clinosim.modules.drug_safety.engine import (
    _condition_matches_predicate,
    _load_disease_rules,
    check_candidate_against_disease_state,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Reload rules fresh for each test — the module caches but we only need the
# first-call behavior to assert integrity, so clearing is cheap and avoids
# cross-test interference if a sibling test mutates the cache.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_disease_rule_cache():
    # Only clear if lru_cache (defensive — _load_disease_rules currently
    # uses a plain-def path on first import; be tolerant of either shape).
    if hasattr(_load_disease_rules, "cache_clear"):
        _load_disease_rules.cache_clear()
    yield
    if hasattr(_load_disease_rules, "cache_clear"):
        _load_disease_rules.cache_clear()


# ---------------------------------------------------------------------------
# Predicate: stage_in matches
# ---------------------------------------------------------------------------


def test_predicate_stage_in_matches_tuple_entry():
    """A ``(code, stage)`` tuple with stage in ``stage_in`` must match."""
    pred = {"icd_prefix": ["N18"], "stage_in": ["CKD G3b", "CKD G4", "CKD G5"]}
    assert _condition_matches_predicate(("N18", "CKD G4"), pred) is True


def test_predicate_stage_in_rejects_out_of_set_stage():
    pred = {"icd_prefix": ["N18"], "stage_in": ["CKD G4", "CKD G5"]}
    assert _condition_matches_predicate(("N18", "CKD G3a"), pred) is False


def test_predicate_stage_in_rejects_bare_string_without_stage():
    """A rule with ``stage_in`` must NOT match a bare-string code (no stage
    information carried) — the caller lost context, so we fail closed."""
    pred = {"icd_prefix": ["N18"], "stage_in": ["CKD G4"]}
    assert _condition_matches_predicate("N18", pred) is False


def test_predicate_without_stage_in_matches_bare_string_as_before():
    """Backward compat: a rule without ``stage_in`` keeps the pre-#1769
    prefix-only matching for plain code strings."""
    pred = {"icd_prefix": ["N18.4", "N18.5", "N18.6"]}
    assert _condition_matches_predicate("N18.4", pred) is True
    assert _condition_matches_predicate("N18", pred) is False


def test_predicate_without_stage_in_matches_tuple_as_before():
    """A tuple entry falls back to code-only matching when ``stage_in``
    is absent from the predicate."""
    pred = {"icd_prefix": ["I50"]}
    assert _condition_matches_predicate(("I50.32", "NYHA III"), pred) is True


# ---------------------------------------------------------------------------
# Rule registration: metformin-in-ckd-stage-3b-5 rule exists and matches
# ---------------------------------------------------------------------------


def test_metformin_ckd_rule_registered():
    rules = _load_disease_rules()
    ids = [r.get("id") for r in rules]
    assert "metformin-in-ckd-stage-3b-5" in ids, (
        f"disease_contraindications.yaml must register the Metformin-CKD "
        f"rule for the activator's initial-activation guard. Got: {ids}"
    )


# ---------------------------------------------------------------------------
# End-to-end: check_candidate_against_disease_state blocks Metformin at
# CKD G3b, G4, G5 but permits it at G1, G2, G3a (where the FDA label
# allows standard-dose use).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ["CKD G3b", "CKD G4", "CKD G5"])
def test_metformin_blocked_at_advanced_ckd(stage: str):
    verdicts = check_candidate_against_disease_state(
        "Metformin",
        [("N18", stage)],
    )
    assert any(v.rule_id == "metformin-in-ckd-stage-3b-5" for v in verdicts), (
        f"Metformin must be blocked at N18 stage {stage!r}. Verdicts: {[(v.rule_id, v.severity) for v in verdicts]}"
    )


@pytest.mark.parametrize("stage", ["CKD G1", "CKD G2", "CKD G3a", ""])
def test_metformin_not_blocked_at_early_ckd_or_no_stage(stage: str):
    """Metformin remains permitted at earlier CKD stages (FDA allows
    standard dose at eGFR >= 45). The initial-activation guard only
    engages at G3b and beyond."""
    verdicts = check_candidate_against_disease_state(
        "Metformin",
        [("N18", stage)],
    )
    assert not any(v.rule_id == "metformin-in-ckd-stage-3b-5" for v in verdicts), (
        f"Metformin must NOT be blocked at N18 stage {stage!r}. Verdicts: {[(v.rule_id, v.severity) for v in verdicts]}"
    )


def test_metformin_not_blocked_when_patient_has_no_n18():
    verdicts = check_candidate_against_disease_state(
        "Metformin",
        [("E11.9", "HbA1c 7.2%"), ("I10", "")],
    )
    assert not any(v.rule_id == "metformin-in-ckd-stage-3b-5" for v in verdicts)


# ---------------------------------------------------------------------------
# Backward compat: existing NSAID-vs-disease rules keep working unchanged.
# ---------------------------------------------------------------------------


def test_nsaid_in_heart_failure_still_fires_with_bare_strings():
    """The pre-existing NSAID rules match on bare-string condition codes
    only — this PR must not regress that path."""
    verdicts = check_candidate_against_disease_state("Ibuprofen", ["I50"])
    assert any(v.rule_id == "nsaid-in-heart-failure" for v in verdicts)


def test_nsaid_in_heart_failure_still_fires_with_tuple_entries():
    """Mixed-shape input must also work: NSAID-vs-HF rule has no
    ``stage_in``, so tuple entries match via code only."""
    verdicts = check_candidate_against_disease_state(
        "Ibuprofen",
        [("I50.32", "NYHA III")],
    )
    assert any(v.rule_id == "nsaid-in-heart-failure" for v in verdicts)
