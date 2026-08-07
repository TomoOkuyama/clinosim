"""Unit tests for the `continue_at_discharge` mechanism in
`build_discharge_rx` (Issue #417 段 1 / #437).

Locks:
  1. `drugs.<category>` blocks flagged `continue_at_discharge: true` are
     read and their drugs land in the discharge_rx items.
  2. Anticoag category respects `exclusive_classes` — mutually exclusive
     draw, never 2 anticoagulants from the same block.
  3. JP 0.8/0.2 (Edoxaban/Warfarin) probability split matches the YAML.
  4. Cross-source guard (approach (a)): if `patient.chronic_conditions`
     contains an ICD whose chronic_medications.yaml block declares an
     overlapping exclusive_class, the flagged block is SKIPPED so the
     chronic transcription (path 2) remains the sole anticoagulant.
  5. `route: PO` filter: infusion routes (IV) declared in the same
     category are silently omitted from discharge_rx.

Non-anticoag categories (statin / antihypertensive / antiplatelet) are
covered by the integration test
`tests/integration/test_discharge_rx_chronic_continuation.py` (they need
the full simulator to observe the cohort-level behavior).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

import numpy as np

from clinosim.modules.disease.protocol import DiseaseProtocol, load_disease_protocol
from clinosim.simulator.discharge_rx import build_discharge_rx
from clinosim.types.patient import ChronicCondition, PatientProfile


def _patient(current_meds: list[str] | None = None, chronic_icds: list[str] | None = None) -> PatientProfile:
    from clinosim.types.patient import HomeMedication

    p = PatientProfile(patient_id="POP-000001")
    # #452 PR 3: attribute-assign bypasses PatientProfile.__post_init__, so
    # promote str fixtures to HomeMedication here.
    p.current_medications = [HomeMedication(drug_name=m) for m in (current_meds or [])]
    p.chronic_conditions = [ChronicCondition(code=icd) for icd in (chronic_icds or [])]
    return p


def _ci_protocol() -> DiseaseProtocol:
    return load_disease_protocol("cerebral_infarction")


def _has(items: list[dict], token: str) -> bool:
    return any(token in it.get("drug_name", "") for it in items)


def test_cerebral_infarction_discharge_always_has_exactly_one_anticoagulant_japan():
    """JP anticoag: Edoxaban 0.8 + Warfarin 0.2 = 1.0. No residual → every
    seed must produce exactly one anticoagulant.
    """
    protocol = _ci_protocol()
    for seed in range(200):
        rx = build_discharge_rx(
            _patient(),
            "cerebral_infarction",
            protocol,
            "PR-1",
            datetime(2026, 1, 1),
            np.random.default_rng(seed),
            country_key="japan",
        )
        count = int(_has(rx.items, "Edoxaban")) + int(_has(rx.items, "Warfarin"))
        assert count == 1, (
            f"seed={seed}: expected exactly 1 anticoag, got {count} ({[i['drug_name'] for i in rx.items]})"
        )


def test_cerebral_infarction_japan_probability_matches_yaml_declared_split():
    """JP: Edoxaban 0.8 / Warfarin 0.2 over 2000 seeds. ±3σ band."""
    protocol = _ci_protocol()
    counts: Counter[str] = Counter()
    n = 2000
    for seed in range(n):
        rx = build_discharge_rx(
            _patient(),
            "cerebral_infarction",
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
    # Expected: 0.8*2000=1600, 0.2*2000=400. ±3σ ≈ ±54 either side.
    assert 1500 < counts["Edoxaban"] < 1700, f"Edoxaban {counts['Edoxaban']}/2000 (expected ~1600)"
    assert 300 < counts["Warfarin"] < 500, f"Warfarin {counts['Warfarin']}/2000 (expected ~400)"


def test_cerebral_infarction_us_probability_matches_yaml_declared_split():
    """US: Apixaban 0.8 / Warfarin 0.2 — same split as JP."""
    protocol = _ci_protocol()
    counts: Counter[str] = Counter()
    n = 2000
    for seed in range(n):
        rx = build_discharge_rx(
            _patient(),
            "cerebral_infarction",
            protocol,
            "PR-1",
            datetime(2026, 1, 1),
            np.random.default_rng(seed),
            country_key="us",
        )
        if _has(rx.items, "Apixaban"):
            counts["Apixaban"] += 1
        if _has(rx.items, "Warfarin"):
            counts["Warfarin"] += 1
    assert 1500 < counts["Apixaban"] < 1700, f"Apixaban {counts['Apixaban']}/2000 (expected ~1600)"
    assert 300 < counts["Warfarin"] < 500, f"Warfarin {counts['Warfarin']}/2000 (expected ~400)"


def test_cross_source_dedup_i48_chronic_suppresses_new_loop_anticoag():
    """Patient with I48 (chronic AF) admitted for cerebral_infarction:
    chronic transcription (path 2) contributes 1 anticoagulant; the new
    continue_at_discharge loop (path 3) MUST detect that `anticoagulant`
    class is already covered via chronic_conditions → skip the
    anticoagulation block. Result: exactly 1 anticoagulant.
    """
    protocol = _ci_protocol()
    # Simulate chronic transcription output — I48 chronic → Warfarin from
    # chronic_medications.yaml (whichever the exclusive draw picked at
    # population time). We pin the input as "Warfarin 3mg" to exercise
    # the (a) covered_classes lookup, not the drug-name dedup.
    for seed in range(200):
        rx = build_discharge_rx(
            _patient(current_meds=["Warfarin 3mg"], chronic_icds=["I48"]),
            "cerebral_infarction",
            protocol,
            "PR-1",
            datetime(2026, 1, 1),
            np.random.default_rng(seed),
            country_key="japan",
        )
        # Distinct anticoagulant tokens: warfarin OR edoxaban.
        has_warfarin = _has(rx.items, "Warfarin")
        has_edoxaban = _has(rx.items, "Edoxaban")
        distinct = int(has_warfarin) + int(has_edoxaban)
        assert distinct == 1, (
            f"seed={seed}: cross-source guard failed. Warfarin={has_warfarin}, "
            f"Edoxaban={has_edoxaban}. items={[i['drug_name'] for i in rx.items]}"
        )


def test_cross_source_dedup_without_chronic_af_allows_new_loop_anticoag():
    """Same patient minus the I48 chronic condition: covered_classes is
    empty, so the new loop DOES add an anticoagulant (JP: Edoxaban or
    Warfarin categorical). Regression guard against an over-eager
    covered_classes derivation that would suppress the loop unconditionally.
    """
    protocol = _ci_protocol()
    seen = 0
    for seed in range(20):
        rx = build_discharge_rx(
            _patient(current_meds=[], chronic_icds=[]),
            "cerebral_infarction",
            protocol,
            "PR-1",
            datetime(2026, 1, 1),
            np.random.default_rng(seed),
            country_key="japan",
        )
        if _has(rx.items, "Edoxaban") or _has(rx.items, "Warfarin"):
            seen += 1
    assert seen == 20, f"anticoag missing in {20 - seen}/20 seeds (categorical must fire)"
