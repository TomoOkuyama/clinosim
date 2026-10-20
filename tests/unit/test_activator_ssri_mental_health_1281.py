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
    # Severity band (optional). Required for SNRI / atypical AD
    # tests on F32 / F33 / F41.1 after the Issue #1137 cluster
    # axis 6 severity-gated prescribing shipped — see
    # ``_derive_home_medications`` ``requires_stage_in`` filter.
    stage: str = ""


SSRI_DRUGS = ("sertraline", "escitalopram", "fluoxetine", "paroxetine")


def _sample(country: str, code: str, n: int, stage: str = "") -> list[list[str]]:
    return [
        [
            m.drug_name
            for m in _derive_home_medications(
                [_Cond(code=code, stage=stage)], np.random.default_rng(s), country=country
            )
        ]
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


def test_jp_locale_uses_japanese_ad_display_1281_1314() -> None:
    """JP locale routes through `drug_ja` so `drug_name_ja` carries the
    kana/kanji form (e.g. セルトラリン). Updated for Issue #1314:
    Fluoxetine is NOT PMDA-approved for Japan and is filtered out by
    the ``locale_exclude`` YAML field, so it no longer appears in JP
    F32 samples — the assertion now covers the remaining SSRI + SNRI +
    atypical-AD JP-approved drugs.
    """
    # Fixture may draw the no-AD branch — sweep a few seeds to find
    # a positive sample. F32 3-class probabilities sum ~= 0.86 after
    # Fluoxetine's JP exclusion.
    got_ja = None
    for seed in range(50):
        m = _derive_home_medications([_Cond(code="F32")], np.random.default_rng(seed), country="JP")
        for entry in m:
            if entry.drug_name_ja:
                got_ja = entry.drug_name_ja
                break
        if got_ja is not None:
            break
    # PMDA-approved AD subset: Sertraline / Escitalopram (SSRI), Venlafaxine
    # / Duloxetine (SNRI), Mirtazapine (atypical AD). Fluoxetine NOT here.
    assert got_ja in (
        "セルトラリン",
        "エスシタロプラム",
        "ベンラファキシン",
        "デュロキセチン",
        "ミルタザピン",
    ), got_ja
    assert got_ja != "フルオキセチン", "Fluoxetine must not appear on JP samples (Issue #1314)"


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
    """F32 depression cohort at moderate+ severity: SNRI (Venlafaxine
    or Duloxetine) emerges only on patients who did NOT already sample
    an SSRI — the ``ssri-plus-snri`` serotonin-syndrome gate drops the
    second serotonergic agent at the activator CPOE check. Pre-gate
    the raw SNRI roll probability is ~15 %; post-gate the observed
    SNRI retention rate is roughly ``P(SNRI roll) × P(no SSRI roll)``
    ≈ 15 % × 35 % ≈ 5 %. Band kept generous (2-10 %) to absorb RNG
    noise at n=1000. Severity gate (axis 6) requires the stage
    fixture — mild cohorts correctly get zero SNRI."""
    hits = sum(
        1 for s in _sample("US", "F32", n=1000, stage="PHQ-9 moderate") if any(d.lower() in SNRI_DRUGS for d in s)
    )
    assert 0.02 * 1000 <= hits <= 0.10 * 1000, f"F32 SNRI rate {hits}/1000 outside 2-10 %"


def test_f32_atypical_class_fires_in_expected_band_us() -> None:
    """F32 depression cohort at moderately severe + severe severity:
    ~6 % receive Mirtazapine (atypical class). Severity gate (axis 6)
    requires the stage fixture — mild / moderate cohorts correctly
    get zero Mirtazapine (atypical is augmentation therapy)."""
    hits = sum(
        1
        for s in _sample("US", "F32", n=1000, stage="PHQ-9 moderately severe")
        if any(d.lower() in ATYPICAL_DRUGS for d in s)
    )
    assert 0.03 * 1000 <= hits <= 0.10 * 1000, f"F32 atypical rate {hits}/1000 outside 3-10 %"


def test_f32_ssri_plus_snri_combination_is_always_dropped() -> None:
    """Audit s103: chronic SSRI + SNRI co-prescription is NOT
    standard-of-care — both mechanisms raise 5-HT availability and the
    pair multiplies serotonin-syndrome risk without evidence of
    additive efficacy. APA 2010 / VA-DoD 2022 depression guidelines
    recommend switching with washout rather than combining, and
    augmentation of an SSRI/SNRI uses a non-serotonergic adjunct
    (Mirtazapine, Bupropion). The activator CPOE gate fires the
    ``ssri-plus-snri`` rule (severity=major) so the second
    serotonergic candidate is dropped — the combination must NEVER
    co-exist on ``current_medications`` for any seed.

    This test previously asserted the opposite ("SSRI + SNRI combo
    SHOULD fire") on the premise that STAR*D-style augmentation
    permits it. That premise was wrong — STAR*D's augmentation step
    is SSRI + non-SSRI/SNRI (bupropion, buspirone, lithium) or SSRI
    switch, never SSRI + SNRI concurrent."""
    for seed in range(1000):
        meds = _derive_home_medications(
            [_Cond(code="F32", stage="PHQ-9 moderate")], np.random.default_rng(seed), country="US"
        )
        names = [m.drug_name.lower() for m in meds]
        has_ssri = any(d in SSRI_DRUGS for d in names)
        has_snri = any(d in SNRI_DRUGS for d in names)
        assert not (has_ssri and has_snri), f"seed={seed}: ssri-plus-snri gate failed — meds={names}"


def test_f41_1_benzodiazepine_fires_only_at_severe_and_non_elderly() -> None:
    """Issue #1137 cluster axis 8 — benzodiazepine (Lorazepam /
    Alprazolam) emits as a short-term rescue therapy ONLY for
    F41.1 GAD-7 severe cohort AND only for non-geriatric patients
    (age < 65 per Beers Criteria 2023).

    Validates three gates:
      1. severity gate: GAD-7 severe → emits; mild/moderate → never.
      2. age gate (Beers): age ≥ 65 → never emits regardless of severity.
      3. baseline rate: ~30-50 % of severe non-elderly cohort receives
         a benzo (literature APA real-world prescribing).
    """
    benzo_drugs = {"lorazepam", "alprazolam"}

    # Severe, young — should fire at ~30-50 %
    severe_young_hits = sum(
        1
        for s in range(500)
        if any(
            d.lower() in benzo_drugs
            for d in [
                m.drug_name
                for m in _derive_home_medications(
                    [_Cond(code="F41.1", stage="GAD-7 severe")],
                    np.random.default_rng(s),
                    country="US",
                    patient_age=40,
                )
            ]
        )
    )
    assert 0.25 * 500 <= severe_young_hits <= 0.55 * 500, (
        f"GAD-7 severe benzo rate {severe_young_hits}/500 outside 25-55 % band"
    )

    # Severe, elderly — Beers gate should suppress
    severe_old_hits = sum(
        1
        for s in range(500)
        if any(
            d.lower() in benzo_drugs
            for d in [
                m.drug_name
                for m in _derive_home_medications(
                    [_Cond(code="F41.1", stage="GAD-7 severe")],
                    np.random.default_rng(s),
                    country="US",
                    patient_age=75,
                )
            ]
        )
    )
    assert severe_old_hits == 0, f"Beers gate failed: {severe_old_hits}/500 elderly got benzo"

    # Mild, young — severity gate should suppress
    mild_hits = sum(
        1
        for s in range(500)
        if any(
            d.lower() in benzo_drugs
            for d in [
                m.drug_name
                for m in _derive_home_medications(
                    [_Cond(code="F41.1", stage="GAD-7 mild")],
                    np.random.default_rng(s),
                    country="US",
                    patient_age=40,
                )
            ]
        )
    )
    assert mild_hits == 0, f"severity gate failed: {mild_hits}/500 mild patients got benzo"


def test_f41_1_snri_first_line_higher_than_f32() -> None:
    """F41.1 GAD at moderate severity: SNRI first-line (APA / VA-DoD).
    Compare at matched severity against F32 moderate so the SNRI
    probability shape difference is visible. F41.1 SNRI candidates
    carry higher base probability than F32 (0.15 + 0.10 vs 0.08 +
    0.07), so the gate-matched sample must retain the ordering."""
    f32_snri = sum(
        1 for s in _sample("US", "F32", n=500, stage="PHQ-9 moderate") if any(d.lower() in SNRI_DRUGS for d in s)
    )
    f41_snri = sum(
        1 for s in _sample("US", "F41.1", n=500, stage="GAD-7 moderate") if any(d.lower() in SNRI_DRUGS for d in s)
    )
    assert f41_snri > f32_snri, f"F41.1 SNRI ({f41_snri}) should exceed F32 SNRI ({f32_snri})"


def test_snri_selection_is_mutually_exclusive_within_class() -> None:
    """`exclusive_classes` includes `snri` — a patient gets at most one
    SNRI (Venlafaxine XOR Duloxetine, never both)."""
    for seed in range(500):
        meds = _derive_home_medications([_Cond(code="F32")], np.random.default_rng(seed), country="US")
        names = [m.drug_name.lower() for m in meds]
        snri_hits = [d for d in names if d in SNRI_DRUGS]
        assert len(snri_hits) <= 1, f"multiple SNRIs on one patient: {snri_hits}"
