"""`build_discharge_rx` anticoagulant exclusivity tests (Issue #432).

The disease-protocol `discharge_oral` block may declare `exclusive_classes`
+ per-entry `drug_class` (same schema as chronic_medications.yaml). Drugs
whose class is in the exclusive list MUST be selected via a categorical
draw (at most one from the class), never emitted unconditionally.

Pulmonary embolism is the load-bearing case: prior to Issue #432 the block
listed Warfarin 1.0 + Edoxaban 1.0 (JP) with no probability gate — every
PE discharge received 2 oral anticoagulants. This test locks the fix and
prevents regression to unconditional emit.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

import numpy as np

from clinosim.modules.disease.protocol import DiseaseProtocol, load_disease_protocol
from clinosim.simulator.discharge_rx import build_discharge_rx


def _pe_protocol() -> DiseaseProtocol:
    return load_disease_protocol("pulmonary_embolism")


def _has(items: list[dict], drug: str) -> bool:
    return any(drug in it.get("drug_name", "") for it in items)


def test_pe_discharge_never_has_warfarin_and_edoxaban_together_japan(patient_factory):
    """Warfarin + Edoxaban MUST NEVER co-appear in a single PE discharge Rx."""
    protocol = _pe_protocol()
    both = 0
    for seed in range(1000):
        rx = build_discharge_rx(
            patient_factory(current_meds=[]),
            "pulmonary_embolism",
            protocol,
            "PR-1",
            datetime(2026, 1, 1),
            np.random.default_rng(seed),
            country_key="japan",
        )
        if _has(rx.items, "Warfarin") and _has(rx.items, "Edoxaban"):
            both += 1
    assert both == 0, f"PE JP Warfarin+Edoxaban concurrent: {both}/1000 (must be 0)"


def test_pe_discharge_never_has_rivaroxaban_and_apixaban_together_us(patient_factory):
    """US: Rivaroxaban + Apixaban MUST NEVER co-appear."""
    protocol = _pe_protocol()
    both = 0
    for seed in range(1000):
        rx = build_discharge_rx(
            patient_factory(current_meds=[]),
            "pulmonary_embolism",
            protocol,
            "PR-1",
            datetime(2026, 1, 1),
            np.random.default_rng(seed),
            country_key="us",
        )
        if _has(rx.items, "Rivaroxaban") and _has(rx.items, "Apixaban"):
            both += 1
    assert both == 0, f"PE US Rivaroxaban+Apixaban concurrent: {both}/1000 (must be 0)"


def test_pe_discharge_japan_probability_matches_yaml_declared_split(patient_factory):
    """JP: Edoxaban 0.8 / Warfarin 0.2 — each rate must land in a ~3-sigma
    interval so authors know a YAML swap on those fields would be caught."""
    protocol = _pe_protocol()
    counts: Counter[str] = Counter()
    n = 2000
    for seed in range(n):
        rx = build_discharge_rx(
            patient_factory(current_meds=[]),
            "pulmonary_embolism",
            protocol,
            "PR-1",
            datetime(2026, 1, 1),
            np.random.default_rng(seed),
            country_key="japan",
        )
        if _has(rx.items, "Edoxaban"):
            counts["Edoxaban"] += 1
        if _has(rx.items, "Warfarin"):
            counts["Warfarin"] += 1
    # Expected: 0.8*2000=1600, 0.2*2000=400. ±3σ tolerance.
    assert 1500 < counts["Edoxaban"] < 1700, f"Edoxaban rate {counts['Edoxaban']}/2000 (expected ~1600)"
    assert 300 < counts["Warfarin"] < 500, f"Warfarin rate {counts['Warfarin']}/2000 (expected ~400)"


def test_pe_discharge_us_probability_matches_yaml_declared_split(patient_factory):
    """US: Rivaroxaban 0.5 / Apixaban 0.5 — both ~1000/2000."""
    protocol = _pe_protocol()
    counts: Counter[str] = Counter()
    n = 2000
    for seed in range(n):
        rx = build_discharge_rx(
            patient_factory(current_meds=[]),
            "pulmonary_embolism",
            protocol,
            "PR-1",
            datetime(2026, 1, 1),
            np.random.default_rng(seed),
            country_key="us",
        )
        if _has(rx.items, "Rivaroxaban"):
            counts["Rivaroxaban"] += 1
        if _has(rx.items, "Apixaban"):
            counts["Apixaban"] += 1
    assert 900 < counts["Rivaroxaban"] < 1100, f"Rivaroxaban {counts['Rivaroxaban']}/2000 (expected ~1000)"
    assert 900 < counts["Apixaban"] < 1100, f"Apixaban {counts['Apixaban']}/2000 (expected ~1000)"


def test_pe_discharge_always_has_exactly_one_anticoagulant_japan(patient_factory):
    """Sum of the two JP probabilities is 1.0 → NO residual "no drug" branch
    should fire. Every discharge MUST have exactly one anticoagulant."""
    protocol = _pe_protocol()
    for seed in range(200):
        rx = build_discharge_rx(
            patient_factory(current_meds=[]),
            "pulmonary_embolism",
            protocol,
            "PR-1",
            datetime(2026, 1, 1),
            np.random.default_rng(seed),
            country_key="japan",
        )
        count = int(_has(rx.items, "Edoxaban")) + int(_has(rx.items, "Warfarin"))
        assert count == 1, (
            f"seed={seed}: expected exactly 1 anticoag (Warfarin XOR Edoxaban), got {count} "
            f"({[i['drug_name'] for i in rx.items]})"
        )
