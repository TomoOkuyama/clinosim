"""Antidepressant chronic-med derivation for F32/F33/F41.1 (#1281).

Pre-#1281 the chronic-medications dispatcher had no entry for the
mental-health ICD codes, so every F32 (depressive episode) and F33
(recurrent depressive disorder) patient received zero antidepressants
despite the diagnosis being planted on `chronic_conditions`
(p=10k s=354: 683 US and 369 JP diagnosed, 0 treated). Other chronic
conditions (HTN → Amlodipine, T2DM → Metformin, dyslip → Atorvastatin,
COPD → Tiotropium) already had generators in `chronic_medications.yaml`.

Fix adds F32, F33, F41.1 entries with mutually-exclusive SSRI class
(Sertraline / Escitalopram / Fluoxetine / Paroxetine) at APA / VA-DoD
first-line coverage (~65-75 % for depression, ~60 % for anxiety —
matches SAMHSA per-diagnosis treatment rates for insured adults).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from clinosim.modules.patient.activator import _derive_home_medications

pytestmark = pytest.mark.unit


@dataclass
class _Cond:
    code: str


SSRI_DRUGS = ("sertraline", "escitalopram", "fluoxetine", "paroxetine")


def _sample(country: str, code: str, n: int) -> list[list[str]]:
    return [
        [m.drug_name for m in _derive_home_medications([_Cond(code=code)], np.random.default_rng(s), country=country)]
        for s in range(n)
    ]


def test_f32_receives_ssri_at_expected_rate_us() -> None:
    """F32 depressive episode → ~65 % SSRI (target 60-75 %)."""
    samples = _sample("US", "F32", n=500)
    hits = sum(1 for s in samples if any(d.lower() in SSRI_DRUGS for d in s))
    assert 0.55 * 500 <= hits <= 0.80 * 500, f"F32 SSRI rate {hits}/500 out of 55-80 % band"


def test_f33_receives_ssri_at_expected_rate_us() -> None:
    """F33 recurrent depressive disorder → ~72 % SSRI."""
    samples = _sample("US", "F33", n=500)
    hits = sum(1 for s in samples if any(d.lower() in SSRI_DRUGS for d in s))
    assert 0.60 * 500 <= hits <= 0.85 * 500, f"F33 SSRI rate {hits}/500 out of 60-85 % band"


def test_f41_1_receives_ssri_at_expected_rate_us() -> None:
    """F41.1 GAD → ~60 % SSRI/SNRI (first-line for anxiety)."""
    samples = _sample("US", "F41.1", n=500)
    hits = sum(1 for s in samples if any(d.lower() in SSRI_DRUGS for d in s))
    assert 0.50 * 500 <= hits <= 0.75 * 500, f"F41.1 SSRI rate {hits}/500 out of 50-75 % band"


def test_ssri_selection_is_mutually_exclusive() -> None:
    """`exclusive_classes: [ssri]` guarantees at most one SSRI per patient.
    Regression guard against a Bernoulli-style multi-SSRI cocktail."""
    samples = _sample("US", "F32", n=500)
    for s in samples:
        ssri_hits = [d for d in s if d.lower() in SSRI_DRUGS]
        assert len(ssri_hits) <= 1, f"multiple SSRIs on one patient: {ssri_hits}"


def test_jp_locale_uses_japanese_ssri_display() -> None:
    """JP locale routes through `drug_ja` so `drug_name_ja` carries the
    kana/kanji form (e.g. セルトラリン)."""
    # Fixture may draw the no-SSRI branch — sweep a few seeds to find
    # a positive sample. F32's SSRI probabilities sum to 0.65.
    got_ja = None
    for seed in range(50):
        m = _derive_home_medications([_Cond(code="F32")], np.random.default_rng(seed), country="JP")
        for entry in m:
            if entry.drug_name_ja:
                got_ja = entry.drug_name_ja
                break
        if got_ja is not None:
            break
    assert got_ja in ("セルトラリン", "エスシタロプラム", "フルオキセチン"), got_ja


def test_non_mental_health_conditions_unchanged() -> None:
    """Regression: HTN (I10) still selects Amlodipine + Candesartan, no
    SSRI leakage."""
    for seed in range(30):
        meds = _derive_home_medications([_Cond(code="I10")], np.random.default_rng(seed), country="US")
        names = [m.drug_name for m in meds]
        assert not any(d.lower() in SSRI_DRUGS for d in names), f"SSRI leaked into HTN cohort: {names}"
        # At least one HTN drug is present per current YAML shape.
        assert any(d in ("Amlodipine", "Candesartan") for d in names)


def test_multi_diagnosis_f32_with_htn_gets_both() -> None:
    """A patient with F32 + I10 gets an SSRI *and* an HTN drug (independent
    per-condition draws)."""
    # Sweep seeds so we deterministically find a sample carrying both.
    for seed in range(50):
        meds = _derive_home_medications(
            [_Cond(code="F32"), _Cond(code="I10")],
            np.random.default_rng(seed),
            country="US",
        )
        names = [m.drug_name for m in meds]
        has_ssri = any(d.lower() in SSRI_DRUGS for d in names)
        has_htn = any(d in ("Amlodipine", "Candesartan") for d in names)
        if has_ssri and has_htn:
            return
    pytest.fail("no F32+I10 combined seed produced both an SSRI and an HTN drug")


# ---------------------------------------------------------------------------
# SNRI + atypical augmentation classes (#1281 second follow-up)
# ---------------------------------------------------------------------------

SNRI_DRUGS = ("venlafaxine", "duloxetine")
ATYPICAL_DRUGS = ("mirtazapine",)


def test_f32_snri_class_fires_in_expected_band_us() -> None:
    """F32 depression cohort: ~15 % receive an SNRI (Venlafaxine or
    Duloxetine — the second-line class alongside SSRI first-line)."""
    hits = sum(1 for s in _sample("US", "F32", n=1000) if any(d.lower() in SNRI_DRUGS for d in s))
    assert 0.08 * 1000 <= hits <= 0.22 * 1000, f"F32 SNRI rate {hits}/1000 outside 8-22 %"


def test_f32_atypical_class_fires_in_expected_band_us() -> None:
    """F32 depression cohort: ~6 % receive Mirtazapine (atypical class)."""
    hits = sum(1 for s in _sample("US", "F32", n=1000) if any(d.lower() in ATYPICAL_DRUGS for d in s))
    assert 0.03 * 1000 <= hits <= 0.10 * 1000, f"F32 atypical rate {hits}/1000 outside 3-10 %"


def test_f32_augmentation_pattern_ssri_plus_snri_exists() -> None:
    """Real STAR*D augmentation: some F32 patients on BOTH an SSRI AND
    an SNRI (~10-15 % of treated). Confirm the multi-class exclusive
    design permits this cross-class combination."""
    found_combo = False
    for seed in range(1000):
        meds = _derive_home_medications([_Cond(code="F32")], np.random.default_rng(seed), country="US")
        names = [m.drug_name.lower() for m in meds]
        if any(d in SSRI_DRUGS for d in names) and any(d in SNRI_DRUGS for d in names):
            found_combo = True
            break
    assert found_combo, "SSRI + SNRI augmentation combination never fires across 1000 seeds"


def test_f41_1_snri_first_line_higher_than_f32() -> None:
    """F41.1 GAD: SNRI probability is bumped vs F32 because APA / VA-DoD
    list SNRI as ALSO first-line for anxiety (vs second-line for
    depression)."""
    f32_snri = sum(1 for s in _sample("US", "F32", n=500) if any(d.lower() in SNRI_DRUGS for d in s))
    f41_snri = sum(1 for s in _sample("US", "F41.1", n=500) if any(d.lower() in SNRI_DRUGS for d in s))
    assert f41_snri > f32_snri, f"F41.1 SNRI ({f41_snri}) should exceed F32 SNRI ({f32_snri})"


def test_snri_selection_is_mutually_exclusive_within_class() -> None:
    """`exclusive_classes` includes `snri` — a patient gets at most one
    SNRI (Venlafaxine XOR Duloxetine, never both)."""
    for seed in range(500):
        meds = _derive_home_medications([_Cond(code="F32")], np.random.default_rng(seed), country="US")
        names = [m.drug_name.lower() for m in meds]
        snri_hits = [d for d in names if d in SNRI_DRUGS]
        assert len(snri_hits) <= 1, f"multiple SNRIs on one patient: {snri_hits}"
