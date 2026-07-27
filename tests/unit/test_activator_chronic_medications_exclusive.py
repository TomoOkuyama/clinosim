"""Activator chronic-medication sampling exclusivity tests (Issue #432).

Chronic medications defined in ``chronic_medications.yaml`` for a given
ICD code may declare an ``exclusive_classes`` list. Drugs whose
``drug_class`` is in that list MUST be selected via a mutually-exclusive
categorical draw (at most one from the class), never via independent
Bernoulli. Non-listed classes / drugs without a class stay on the
current independent-Bernoulli path so clinically-valid concurrent
regimens (e.g. I50 HF triad, I25 DAPT continuum) are preserved.

Tests here verify:
- I48 / I26 / I82 anticoagulant exclusivity (all-anticoagulant blocks)
- I63 mixed block: anticoagulant exclusive, antiplatelet independent
- I50 / I25 non-exclusive blocks preserve concurrent regimens
- ``medication_flags_from_context`` on_warfarin detection still triggers
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from clinosim.modules.patient.activator import _derive_home_medications
from clinosim.modules.physiology.engine import medication_flags_from_context


@dataclass
class _Cond:
    code: str


def _sample_us(codes: list[str], n: int) -> list[list[str]]:
    """Draw n independent activator samples (US drug names)."""
    return [
        _derive_home_medications([_Cond(code=c) for c in codes], np.random.default_rng(s), country="US")
        for s in range(n)
    ]


# --------------------------------------------------------------------------- #
# I48 anticoagulant exclusivity


def test_I48_never_yields_warfarin_and_apixaban_together():
    samples = _sample_us(["I48"], n=1000)
    both = sum(1 for s in samples if any("Warfarin" in m for m in s) and any("Apixaban" in m for m in s))
    assert both == 0, f"Warfarin+Apixaban chronic concurrent: {both}/1000 (must be 0)"


def test_I48_each_anticoagulant_still_appears_at_expected_rate():
    """I48 = [Warfarin 0.5, Apixaban 0.5] sum=1.0 → each ~50% under
    categorical (no residual 'no drug' branch since sum==1.0)."""
    samples = _sample_us(["I48"], n=1000)
    n_warf = sum(1 for s in samples if any("Warfarin" in m for m in s))
    n_apix = sum(1 for s in samples if any("Apixaban" in m for m in s))
    assert 400 < n_warf < 600, f"Warfarin rate {n_warf}/1000 (expected ~500)"
    assert 400 < n_apix < 600, f"Apixaban rate {n_apix}/1000 (expected ~500)"


# --------------------------------------------------------------------------- #
# I26 / I82 three-drug anticoagulant exclusivity


def test_I26_never_yields_multiple_anticoagulants():
    samples = _sample_us(["I26"], n=1000)
    for s in samples:
        count = sum(1 for tok in ("Rivaroxaban", "Apixaban", "Warfarin") if any(tok in m for m in s))
        assert count <= 1, f"I26 multiple anticoag in one sample: {s}"


def test_I82_never_yields_multiple_anticoagulants():
    samples = _sample_us(["I82"], n=1000)
    for s in samples:
        count = sum(1 for tok in ("Rivaroxaban", "Apixaban", "Warfarin") if any(tok in m for m in s))
        assert count <= 1, f"I82 multiple anticoag in one sample: {s}"


# --------------------------------------------------------------------------- #
# I63 mixed block: anticoag exclusive, antiplatelet independent


def test_I63_anticoagulants_exclusive():
    samples = _sample_us(["I63"], n=1000)
    for s in samples:
        count = sum(1 for tok in ("Warfarin", "Apixaban") if any(tok in m for m in s))
        assert count <= 1, f"I63 multiple anticoag in one sample: {s}"


def test_I63_antiplatelets_can_coexist():
    """Aspirin (0.7) + Clopidogrel (0.3) — independent Bernoulli.
    Expected co-occurrence ≈ 0.7 × 0.3 = 21% → strictly non-zero in 1000."""
    samples = _sample_us(["I63"], n=1000)
    both = sum(1 for s in samples if any("Aspirin" in m for m in s) and any("Clopidogrel" in m for m in s))
    assert both > 100, f"I63 Aspirin+Clopidogrel coexist: {both}/1000 (expected ~210)"


def test_I63_can_yield_anticoag_plus_antiplatelet():
    """Anticoag+antiplatelet chronic concurrent is clinically rare but not
    forbidden (mechanical valve + coronary stent scenarios). Verify the
    combination is not accidentally suppressed by class-level exclusivity
    machinery."""
    samples = _sample_us(["I63"], n=1000)
    any_combo = sum(
        1
        for s in samples
        if (any("Warfarin" in m for m in s) or any("Apixaban" in m for m in s))
        and (any("Aspirin" in m for m in s) or any("Clopidogrel" in m for m in s))
    )
    assert any_combo > 100, f"I63 anticoag+antiplatelet coexist: {any_combo}/1000 (independence lost)"


# --------------------------------------------------------------------------- #
# I50 / I25 non-exclusive blocks preserved


def test_I50_heart_failure_triad_can_coexist():
    """I50 = Furosemide 1.0 + Carvedilol 0.6 + Enalapril 0.5 →
    P(all 3) = 1.0 × 0.6 × 0.5 = 30% → ≥ 200/1000."""
    samples = _sample_us(["I50"], n=1000)
    triad = sum(
        1
        for s in samples
        if any("Furosemide" in m for m in s) and any("Carvedilol" in m for m in s) and any("Enalapril" in m for m in s)
    )
    assert triad > 200, f"I50 HF triad coexist: {triad}/1000 (expected ~300)"


def test_I25_DAPT_pair_can_coexist():
    """I25 = Aspirin 1.0 + Clopidogrel 0.4 → P(both) = 40% → ≥ 250/1000."""
    samples = _sample_us(["I25"], n=1000)
    both = sum(1 for s in samples if any("Aspirin" in m for m in s) and any("Clopidogrel" in m for m in s))
    assert both > 250, f"I25 DAPT coexist: {both}/1000 (expected ~400)"


# --------------------------------------------------------------------------- #
# on_warfarin detection preserved


def test_on_warfarin_detection_fires_for_chronic_warfarin_patient():
    """Regression guard: population-side exclusivity change must NOT
    break ``medication_flags_from_context``'s on_warfarin detection from
    ``patient.current_medications``."""

    class _P:
        current_medications = ["Warfarin 3mg"]

    assert medication_flags_from_context(_P()) == {"on_warfarin": True}


def test_on_warfarin_detection_fires_for_chronic_warfarin_jp():
    """Same regression, JP drug name path."""

    class _P:
        current_medications = ["ワルファリン3mg"]

    assert medication_flags_from_context(_P()) == {"on_warfarin": True}
