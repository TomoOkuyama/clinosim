"""Unit tests for the chronic-medication monitoring pipeline (Issue #757).

Covers the mapping loader (fail-loud validation), the patient-medication
matcher (case-insensitive substring match across EN + JP), and the
per-visit probability gate.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from clinosim.modules.monitoring import (
    load_medication_lab_mapping,
    monitoring_labs_for_patient,
)


class _Med:
    def __init__(self, drug_name: str = "", drug_name_ja: str = "") -> None:
        self.drug_name = drug_name
        self.drug_name_ja = drug_name_ja


def _rng() -> np.random.Generator:
    return np.random.default_rng(42)


# === Mapping loader contract ===


def test_loader_returns_dict_with_expected_keys() -> None:
    mapping = load_medication_lab_mapping()
    assert "warfarin" in mapping, "warfarin mapping required (closes #736)"
    assert set(mapping["warfarin"]["labs"]) == {"PT_INR"}
    assert mapping["warfarin"]["per_visit_probability"] == 1.0


def test_loader_all_entries_have_required_fields() -> None:
    mapping = load_medication_lab_mapping()
    for key, entry in mapping.items():
        assert "matches" in entry and entry["matches"], f"{key} missing matches"
        assert "labs" in entry and entry["labs"], f"{key} missing labs"
        prob = entry["per_visit_probability"]
        assert 0.0 <= prob <= 1.0, f"{key} probability out of range: {prob}"


# === Patient-medication matcher ===


def test_no_meds_returns_empty() -> None:
    assert monitoring_labs_for_patient([], _rng()) == []


def test_warfarin_english_name_matches() -> None:
    labs = monitoring_labs_for_patient([_Med(drug_name="Warfarin 5mg PO")], _rng())
    assert "PT_INR" in labs


def test_warfarin_japanese_name_matches() -> None:
    labs = monitoring_labs_for_patient([_Med(drug_name_ja="ワルファリン 3mg 経口")], _rng())
    assert "PT_INR" in labs


def test_coumadin_trade_name_matches() -> None:
    labs = monitoring_labs_for_patient([_Med(drug_name="Coumadin 5mg")], _rng())
    assert "PT_INR" in labs


def test_unrelated_med_no_match() -> None:
    labs = monitoring_labs_for_patient([_Med(drug_name="Amlodipine 5mg")], _rng())
    assert labs == []


def test_multiple_monitored_meds_labs_deduplicated() -> None:
    # Both metformin AND insulin request HbA1c — must appear only once.
    labs = monitoring_labs_for_patient([_Med(drug_name="Metformin"), _Med(drug_name="Insulin lispro")], _rng())
    assert labs.count("HbA1c") == 1


def test_dict_med_shape_supported() -> None:
    """CIF JSON-deserialized medications are dicts, not dataclasses. Both
    shapes must resolve identically (feedback_o_dual_access pattern)."""
    labs = monitoring_labs_for_patient([{"drug_name": "Warfarin", "drug_name_ja": ""}], _rng())
    assert "PT_INR" in labs


# === Probability gate ===


def test_per_visit_probability_gate_fires_under_seed() -> None:
    """Levothyroxine mapping has per_visit_probability=0.5. Sampling many
    seeds must show roughly half fire — spot check that the gate exists."""
    fires = 0
    total = 200
    for seed in range(total):
        labs = monitoring_labs_for_patient([_Med(drug_name="Levothyroxine 50mcg")], np.random.default_rng(seed))
        if "TSH" in labs:
            fires += 1
    # 40-60 % expected for prob=0.5 over 200 draws
    assert 0.35 * total <= fires <= 0.65 * total, f"expected ~50 % fire rate; got {fires / total:.2%}"


def test_warfarin_probability_1_always_fires() -> None:
    """PT_INR is per_visit_probability=1.0 (every-visit standard-of-care).
    Must fire every time for any seed (closes #736 root cause)."""
    for seed in range(30):
        labs = monitoring_labs_for_patient([_Med(drug_name="Warfarin 5mg")], np.random.default_rng(seed))
        assert "PT_INR" in labs, f"seed={seed} failed to fire PT_INR"


# === Integration smoke — patient shape agnostic ===


def test_integration_shape_matches_patientprofile_current_medications() -> None:
    """Smoke test: real patient shape has ``current_medications: list[HomeMedication]``
    with .drug_name / .drug_name_ja attributes. SimpleNamespace matches
    ``getattr`` access pattern in the engine."""
    patient = SimpleNamespace(
        current_medications=[
            SimpleNamespace(drug_name="Warfarin", drug_name_ja="ワルファリン"),
            SimpleNamespace(drug_name="Amlodipine 5mg", drug_name_ja=""),
        ]
    )
    labs = monitoring_labs_for_patient(patient.current_medications, _rng())
    assert "PT_INR" in labs
