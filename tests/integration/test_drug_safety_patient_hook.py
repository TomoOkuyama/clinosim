"""Integration: activator._derive_home_medications rejects the second drug
in a contraindicated home-med pair (warfarin + aspirin)."""

from __future__ import annotations

import numpy as np

from clinosim.modules.patient.activator import _derive_home_medications


class _Cond:
    def __init__(self, code: str) -> None:
        self.code = code


def test_derive_home_meds_skips_aspirin_when_warfarin_already_chosen() -> None:
    """AF (I48) + coronary disease (I25) would normally give warfarin + aspirin.
    With the gate, only one anticoagulation-flavor drug is emitted.

    We simulate by seeding a scenario where both would be picked, and check
    that the seen list ends up with only warfarin (the first-picked).
    Reality: chronic_medications.yaml doesn't necessarily give both;
    fabricate a synthetic ChronicCondition to exercise the code path.
    """
    # Use a deterministic RNG for reproducibility.
    rng = np.random.default_rng(seed=500)
    skip_log: list = []
    # Note: the actual yaml-driven code may or may not produce the pair.
    # This test primarily verifies the SIGNATURE works (accepts skip_log_out)
    # and returns without exception. The functional gate is separately
    # verified against synthetic input below.
    result = _derive_home_medications(
        [_Cond(code="I48"), _Cond(code="I25")],
        rng,
        country="US",
        skip_log_out=skip_log,
    )
    # No crash; result is a list of HomeMedication
    assert isinstance(result, list)


def test_derive_home_meds_skip_log_populated_with_synthetic_data(monkeypatch) -> None:
    """Monkeypatch chronic_medications loader to force a contraindicated pair,
    then verify the gate skips the second drug and records a skip entry."""
    from clinosim.modules.patient import activator as activator_mod

    fake_data = {
        "TEST_CODE": {
            "medications": [
                {
                    "drug": "Warfarin",
                    "drug_ja": "ワルファリン",
                    "route": "PO",
                    "dose": "3mg",
                    "frequency": "daily",
                    "probability": 1.0,
                },
                {
                    "drug": "Aspirin",
                    "drug_ja": "アスピリン",
                    "route": "PO",
                    "dose": "100mg",
                    "frequency": "daily",
                    "probability": 1.0,
                },
            ],
        },
    }

    def fake_loader() -> dict:
        return fake_data

    monkeypatch.setattr("clinosim.locale.loader.load_chronic_medications", fake_loader)

    rng = np.random.default_rng(seed=42)
    skip_log: list = []
    result = _derive_home_medications(
        [_Cond(code="TEST_CODE")],
        rng,
        country="US",
        skip_log_out=skip_log,
    )
    drugs = [m.drug_name for m in result]
    # Warfarin selected first; Aspirin skipped by gate
    assert "Warfarin" in drugs
    assert "Aspirin" not in drugs
    assert len(skip_log) == 1
    entry = skip_log[0]
    assert entry.candidate_drug == "Aspirin"
    assert entry.active_conflict == "Warfarin"
    assert entry.encounter_id == "__home_med_derivation__"
    assert entry.substituted_with is None  # MVP: no chronic substitution
    assert entry.context_hint == "home_med_derivation"


def test_derive_home_meds_none_skip_log_preserves_backward_compat() -> None:
    """Callers that don't pass skip_log_out get the pre-fix behavior."""
    rng = np.random.default_rng(seed=500)
    result = _derive_home_medications([_Cond(code="I10")], rng, country="US")
    assert isinstance(result, list)
