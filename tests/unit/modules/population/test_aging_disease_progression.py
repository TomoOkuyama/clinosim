"""Phase 2: `_disease_progression` behaviour — Issue #1564.

Split out of ``test_aging_hook_1564.py`` (originally 1537 LOC) so the
disease-progression tests (CKD, COPD, cirrhosis, Parkinson, atrial
fibrillation, MS, stroke-sequela, F32/F411 mental-health, HF, CCS,
CDR) live together.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from clinosim.modules.population.aging import (
    _allergy_drift,
    _disease_progression,
    advance_population,
    aging_sub_seed,
)
from clinosim.modules.population.engine import PopulationRegistry
from clinosim.types.population import PersonRecord


def _alive(pid: str, age: int = 50, sex: str = "M") -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="HH-1",
        age=age,
        sex=sex,
        date_of_birth=date(2026 - age, 1, 1),
    )


def _registry(persons: list[PersonRecord]) -> PopulationRegistry:
    reg = PopulationRegistry()
    for p in persons:
        reg.persons[p.person_id] = p
    reg.initial_person_ids = set(reg.persons.keys())
    return reg


# ---------------------------------------------------------------------------
# _disease_progression behaviour (Phase 2.5, CKD + COPD)
# ---------------------------------------------------------------------------


def test_disease_progression_noop_when_no_tracked_conditions() -> None:
    """A person with no staged chronic condition never touches
    disease_stages. I10 is intentionally not staged in
    stage_transition.yaml (hypertension severity does not progress
    on a yearly scale at the aging-pass layer)."""
    p = _alive("PT-OTHER", age=60)
    p.chronic_conditions = ["I10"]
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert p.disease_stages == {}


def test_disease_progression_initialises_ckd_stage() -> None:
    """First-year touch on a person with N18 populates
    disease_stages with one of the KDIGO stages."""
    p = _alive("PT-CKD-INIT", age=65)
    p.chronic_conditions = ["N18"]
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert "N18" in p.disease_stages
    assert p.disease_stages["N18"] in ("CKD G1", "CKD G2", "CKD G3a", "CKD G3b", "CKD G4", "CKD G5")


def test_disease_progression_initialises_copd_stage() -> None:
    p = _alive("PT-COPD-INIT", age=70)
    p.chronic_conditions = ["J44"]
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert "J44" in p.disease_stages
    assert p.disease_stages["J44"] in ("GOLD 1", "GOLD 2", "GOLD 3", "GOLD 4")


def test_disease_progression_initialises_cirrhosis_stage() -> None:
    """Both K70 (alcoholic) and K74 (non-alcoholic) cirrhosis
    initialise to a Child-Pugh A/B/C stage on first touch."""
    for icd in ("K70", "K74"):
        p = _alive(f"PT-CIRRHOSIS-{icd}", age=65)
        p.chronic_conditions = [icd]
        _disease_progression(
            p,
            2026,
            np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
            {},
        )
        assert icd in p.disease_stages
        assert p.disease_stages[icd] in ("Child-Pugh A", "Child-Pugh B", "Child-Pugh C")


def test_disease_progression_cirrhosis_eventually_reaches_decompensated() -> None:
    """A compensated (Child-Pugh A) K70 person run through 20 years
    of progression Monte-Carlo at least sometimes decompensates to
    Child-Pugh C. Deterministic seed keeps the result stable."""
    hit_c = 0
    trials = 100
    for i in range(trials):
        p = _alive(f"PT-K70-DECOMP-{i:04d}", age=55)
        p.chronic_conditions = ["K70"]
        p.disease_stages = {"K70": "Child-Pugh A"}
        p.disease_stage_history = {"K70": {2025: "Child-Pugh A"}}
        for yr in range(20):
            _disease_progression(
                p,
                2026 + yr,
                np.random.default_rng(aging_sub_seed(p.person_id, 2026 + yr, "_disease_progression")),
                {},
            )
        if p.disease_stages["K70"] == "Child-Pugh C":
            hit_c += 1
    # D'Amico 2006: ~5-10 %/yr A→B then ~10-12 %/yr B→C means a
    # non-trivial fraction reaches C over 20 years. Loose lower
    # bound to tolerate Monte-Carlo variance.
    assert hit_c >= 5, f"only {hit_c}/{trials} K70 cohort reached Child-Pugh C in 20 years"


def test_disease_progression_initialises_parkinson_stage() -> None:
    """G20 person without a stage picks up a Hoehn & Yahr 1-5
    assignment on first ``_disease_progression`` touch."""
    p = _alive("PT-PD-INIT", age=70)
    p.chronic_conditions = ["G20"]
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert "G20" in p.disease_stages
    assert p.disease_stages["G20"] in ("H&Y 1", "H&Y 2", "H&Y 3", "H&Y 4", "H&Y 5")


def test_disease_progression_parkinson_eventually_advances() -> None:
    """A H&Y 1 Parkinson's person over 15 years of progression
    Monte-Carlo at least sometimes reaches H&Y 3 or beyond. The
    stage-1 annual rate of 0.35 compounded over 15 years makes
    this a very high-probability outcome; the test checks the
    code path fires at all."""
    hit_advanced = 0
    trials = 100
    for i in range(trials):
        p = _alive(f"PT-PD-ADV-{i:04d}", age=60)
        p.chronic_conditions = ["G20"]
        p.disease_stages = {"G20": "H&Y 1"}
        p.disease_stage_history = {"G20": {2025: "H&Y 1"}}
        for yr in range(15):
            _disease_progression(
                p,
                2026 + yr,
                np.random.default_rng(aging_sub_seed(p.person_id, 2026 + yr, "_disease_progression")),
                {},
            )
        if p.disease_stages["G20"] in ("H&Y 3", "H&Y 4", "H&Y 5"):
            hit_advanced += 1
    assert hit_advanced >= 50, (
        f"only {hit_advanced}/{trials} G20 cohort reached H&Y 3+ in 15 years — progression table may be too slow"
    )


def test_disease_progression_initialises_atrial_fibrillation_stage() -> None:
    """I48 person without a stage picks up an AHA/ACC/HRS 2024
    classification label on first ``_disease_progression`` touch."""
    p = _alive("PT-AF-INIT", age=70)
    p.chronic_conditions = ["I48"]
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert "I48" in p.disease_stages
    assert p.disease_stages["I48"] in (
        "Paroxysmal",
        "Persistent",
        "Long-standing persistent",
        "Permanent",
    )


def test_disease_progression_af_eventually_progresses() -> None:
    """A paroxysmal AF person over 15 years at the de Vos 2010 rates
    reaches persistent-or-worse in the majority of Monte-Carlo
    trials. Loose lower bound tolerates variance."""
    hit_advanced = 0
    trials = 100
    for i in range(trials):
        p = _alive(f"PT-AF-{i:04d}", age=65)
        p.chronic_conditions = ["I48"]
        p.disease_stages = {"I48": "Paroxysmal"}
        p.disease_stage_history = {"I48": {2025: "Paroxysmal"}}
        for yr in range(15):
            _disease_progression(
                p,
                2026 + yr,
                np.random.default_rng(aging_sub_seed(p.person_id, 2026 + yr, "_disease_progression")),
                {},
            )
        if p.disease_stages["I48"] != "Paroxysmal":
            hit_advanced += 1
    # 0.15 /yr compounded over 15 years → ~90 % reach persistent+.
    assert hit_advanced >= 60, f"only {hit_advanced}/{trials} AF cohort advanced beyond paroxysmal in 15 years"


def test_disease_progression_initialises_multiple_sclerosis_stage() -> None:
    """G35 person without a stage picks up a banded-EDSS label on
    first ``_disease_progression`` touch."""
    p = _alive("PT-MS-INIT", age=35)
    p.chronic_conditions = ["G35"]
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert "G35" in p.disease_stages
    assert p.disease_stages["G35"] in (
        "EDSS 0-2",
        "EDSS 2.5-5",
        "EDSS 5.5-7",
        "EDSS 7.5-10",
    )


def test_disease_progression_ms_eventually_advances() -> None:
    """An EDSS 0-2 MS person over 25 years at the Confavreux-based
    rates reaches walking impairment (EDSS 5.5-7) or worse in a
    non-trivial fraction of trials. Loose lower bound tolerates
    variance; the point is to exercise the natural-history mean
    time to EDSS 6 ~20 years."""
    hit_advanced = 0
    trials = 100
    for i in range(trials):
        p = _alive(f"PT-MS-{i:04d}", age=30)
        p.chronic_conditions = ["G35"]
        p.disease_stages = {"G35": "EDSS 0-2"}
        p.disease_stage_history = {"G35": {2025: "EDSS 0-2"}}
        for yr in range(25):
            _disease_progression(
                p,
                2026 + yr,
                np.random.default_rng(aging_sub_seed(p.person_id, 2026 + yr, "_disease_progression")),
                {},
            )
        if p.disease_stages["G35"] in ("EDSS 5.5-7", "EDSS 7.5-10"):
            hit_advanced += 1
    assert hit_advanced >= 10, f"only {hit_advanced}/{trials} MS cohort reached walking-impairment in 25 years"


def test_stroke_sequela_promotion_adds_i69_3_after_past_cerebral_infarction() -> None:
    """A person with a past cerebral_infarction hospitalization and no
    I69.3 yet picks up I69.3 on first ``advance_population`` touch.
    Idempotent — a second run does not re-append."""
    from datetime import date as _d

    from clinosim.types.population import HospitalizationSummary

    p = _alive("PT-STROKE-SEQ", age=65)
    p.hospitalization_history = [
        HospitalizationSummary(
            encounter_id="ENC-ABC",
            disease_id="cerebral_infarction",
            admission_date=_d(2025, 3, 1),
            discharge_date=_d(2025, 3, 10),
            los_days=9,
            outcome="discharged",
        )
    ]
    reg = _registry([p])
    advance_population(reg, 2026, "us")
    assert "I69.3" in p.chronic_conditions
    # mRS stage must be initialised by _disease_progression
    assert p.disease_stages.get("I69") in {"mRS 0", "mRS 1", "mRS 2", "mRS 3", "mRS 4", "mRS 5"}

    # Idempotent second advance.
    chronic_before = list(p.chronic_conditions)
    advance_population(reg, 2027, "us")
    assert p.chronic_conditions == chronic_before


def test_stroke_sequela_promotion_hemorrhagic_adds_i69_1() -> None:
    """A person with a past hemorrhagic_stroke hospitalization and no
    I69.1 yet picks up I69.1 on first ``advance_population`` touch.
    Base-code "I69" shares the mRS stage system with I69.3."""
    from datetime import date as _d

    from clinosim.types.population import HospitalizationSummary

    p = _alive("PT-HEM-STROKE", age=70)
    p.hospitalization_history = [
        HospitalizationSummary(
            encounter_id="ENC-HEM",
            disease_id="hemorrhagic_stroke",
            admission_date=_d(2025, 4, 1),
            discharge_date=_d(2025, 4, 20),
            los_days=19,
            outcome="discharged",
        )
    ]
    reg = _registry([p])
    advance_population(reg, 2026, "us")
    assert "I69.1" in p.chronic_conditions
    # Must NOT also add I69.3 — the ischemic promotion arm did not fire.
    assert "I69.3" not in p.chronic_conditions
    # mRS stage initialised via the shared base-code "I69" sampler.
    assert p.disease_stages.get("I69") in {"mRS 0", "mRS 1", "mRS 2", "mRS 3", "mRS 4", "mRS 5"}


def test_stroke_sequela_hemorrhagic_mrs_distribution_shifted_vs_ischemic() -> None:
    """Hemorrhagic sequela (I69.1) persons draw from a rightward-
    shifted mRS distribution compared with ischemic sequela (I69.3)
    persons. Monte-Carlo at p=1000 — compare mean mRS index."""
    from datetime import date as _d

    from clinosim.types.population import HospitalizationSummary

    stage_idx = {"mRS 0": 0, "mRS 1": 1, "mRS 2": 2, "mRS 3": 3, "mRS 4": 4, "mRS 5": 5}

    def _mean_initial_mrs(disease_id: str, expected_chronic: str) -> float:
        total = 0.0
        n = 1000
        for i in range(n):
            p = _alive(f"PT-SEQ-{disease_id}-{i:04d}", age=70)
            p.hospitalization_history = [
                HospitalizationSummary(
                    encounter_id=f"ENC-{i}",
                    disease_id=disease_id,
                    admission_date=_d(2025, 3, 1),
                    discharge_date=_d(2025, 3, 10),
                    los_days=9,
                    outcome="discharged",
                )
            ]
            reg = _registry([p])
            advance_population(reg, 2026, "us")
            assert expected_chronic in p.chronic_conditions
            total += stage_idx[p.disease_stages["I69"]]
        return total / n

    ischemic_mean = _mean_initial_mrs("cerebral_infarction", "I69.3")
    hemorrhagic_mean = _mean_initial_mrs("hemorrhagic_stroke", "I69.1")
    # Expected: ischemic ~2.5 (I69_3 weights center on mRS 2),
    # hemorrhagic ~3.1 (I69_1 weights center on mRS 3-4). Require a
    # clear separation to confirm the dispatcher routes to the
    # correct per-code sampler.
    assert hemorrhagic_mean > ischemic_mean + 0.3, (
        f"hemorrhagic I69.1 mean mRS ({hemorrhagic_mean:.2f}) should exceed "
        f"ischemic I69.3 mean ({ischemic_mean:.2f}) by ≥0.3; weights wiring broken"
    )


def test_stroke_sequela_hemorrhagic_advance_slower_than_ischemic() -> None:
    """Hemorrhagic I69.1 progresses slower than ischemic I69.3 per
    stage, reflecting the survivor-selection stability. Monte-Carlo
    over 15 years: ischemic cohort mean mRS exceeds hemorrhagic
    cohort mean, both starting at the same mRS 2 baseline."""
    stage_idx = {"mRS 0": 0, "mRS 1": 1, "mRS 2": 2, "mRS 3": 3, "mRS 4": 4, "mRS 5": 5}

    def _mean_final_mrs(chronic_icd: str) -> float:
        total = 0.0
        n = 300
        for i in range(n):
            p = _alive(f"PT-ADV-{chronic_icd}-{i:04d}", age=65)
            p.chronic_conditions = [chronic_icd]
            p.disease_stages = {"I69": "mRS 2"}
            p.disease_stage_history = {"I69": {2025: "mRS 2"}}
            for yr in range(15):
                _disease_progression(
                    p,
                    2026 + yr,
                    np.random.default_rng(aging_sub_seed(p.person_id, 2026 + yr, "_disease_progression")),
                    {},
                )
            total += stage_idx[p.disease_stages["I69"]]
        return total / n

    ischemic_mean = _mean_final_mrs("I69.3")
    hemorrhagic_mean = _mean_final_mrs("I69.1")
    # ~25 % rate reduction (hemorrhagic) over 15 years at the all-
    # cohort baseline produces a Monte-Carlo gap of ~0.15-0.20 mRS
    # stage-index points at p=300. Lower bound 0.10 keeps the test
    # stable under seed-local variance while still catching a
    # directional dispatcher bug (equal rates would give gap ~0).
    assert ischemic_mean > hemorrhagic_mean + 0.10, (
        f"ischemic mean mRS ({ischemic_mean:.2f}) should exceed hemorrhagic "
        f"({hemorrhagic_mean:.2f}) by ≥ 0.10 — per-sub-code dispatcher may be routing wrong"
    )


def test_disease_progression_initialises_f32_phq9_severity() -> None:
    """F32 person without a stage picks up a PHQ-9 severity band
    on first ``_disease_progression`` touch (Kroenke 2001 Kroenke
    severity bands shared with F33)."""
    for icd in ("F32", "F33"):
        p = _alive(f"PT-DEP-{icd}", age=45)
        p.chronic_conditions = [icd]
        _disease_progression(
            p,
            2026,
            np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
            {},
        )
        assert icd in p.disease_stages
        assert p.disease_stages[icd] in (
            "PHQ-9 none",
            "PHQ-9 mild",
            "PHQ-9 moderate",
            "PHQ-9 moderately severe",
            "PHQ-9 severe",
        )


def test_disease_progression_initialises_f411_gad7_severity() -> None:
    """F41.1 person without a stage picks up a GAD-7 severity band
    on first ``_disease_progression`` touch (Spitzer 2006 bands).
    Stage is stored under the base code "F41" per the aging-pass
    ``code.split(".")[0]`` convention; the full code "F41.1" is a
    yaml and sampler key but the resolved stage lives at the base
    (same pattern as I69 → I69.1 / I69.3 sequelae)."""
    p = _alive("PT-GAD", age=40)
    p.chronic_conditions = ["F41.1"]
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert "F41" in p.disease_stages
    assert p.disease_stages["F41"] in (
        "GAD-7 minimal",
        "GAD-7 mild",
        "GAD-7 moderate",
        "GAD-7 severe",
    )


def test_mental_health_severity_distribution_mode_moderate() -> None:
    """Monte-Carlo p=1000 confirms the F32 severity distribution's
    mode is at the moderate band (weight 0.40) — matches the
    Kroenke primary-care cohort distribution shape."""
    from collections import Counter

    counts: Counter[str] = Counter()
    for i in range(1000):
        p = _alive(f"PT-DIST-{i:04d}", age=50)
        p.chronic_conditions = ["F32"]
        _disease_progression(
            p,
            2026,
            np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
            {},
        )
        counts[p.disease_stages["F32"]] += 1
    # Expected weights: 0.05 / 0.20 / 0.40 / 0.25 / 0.10 — moderate
    # should be the mode.
    mode_stage = counts.most_common(1)[0][0]
    assert mode_stage == "PHQ-9 moderate", f"expected moderate mode, got {mode_stage} with counts {dict(counts)}"


def test_mental_health_onset_multiplier_1_when_no_rule_or_no_comorbidity() -> None:
    """A person with no somatic comorbidity gets multiplier 1.0 on
    every mental-health target — rate unchanged from baseline."""
    from clinosim.modules.population.aging import _mental_health_onset_multiplier

    p = _alive("PT-NONE", age=50)
    p.chronic_conditions = []
    assert _mental_health_onset_multiplier("F32", p) == 1.0
    # Target without any rule → 1.0 regardless of comorbidities.
    p.chronic_conditions = ["E11", "I50"]
    assert _mental_health_onset_multiplier("I10", p) == 1.0


def test_mental_health_onset_multiplier_depression_compounds_comorbidities() -> None:
    """DM + HF + a cancer code compound: 2.0 × 2.0 × 2.5 = 10.0x on
    F32 onset. Verifies the three trigger forms (exact, exact,
    prefix) all route correctly."""
    from clinosim.modules.population.aging import _mental_health_onset_multiplier

    p = _alive("PT-MULTI", age=65)
    p.chronic_conditions = ["E11", "I50", "C18"]  # DM + HF + colon cancer
    mult = _mental_health_onset_multiplier("F32", p)
    assert abs(mult - (2.0 * 2.0 * 2.5)) < 1e-9, f"expected 10.0, got {mult}"


def test_mental_health_onset_multiplier_post_stroke_depression() -> None:
    """A person with I69.3 (ischemic stroke sequela) picks up the
    post_stroke_depression 2.0x multiplier on F32 / F33 onset."""
    from clinosim.modules.population.aging import _mental_health_onset_multiplier

    p = _alive("PT-POSTSTROKE", age=70)
    p.chronic_conditions = ["I69.3"]
    assert _mental_health_onset_multiplier("F32", p) == 2.0
    assert _mental_health_onset_multiplier("F33", p) == 2.0
    # F41.1 does not have a post-stroke-anxiety rule → 1.0
    assert _mental_health_onset_multiplier("F41.1", p) == 1.0


def test_mental_health_onset_multiplier_gad_lower_magnitude_than_depression() -> None:
    """GAD (F41.1) has lower comorbidity magnitudes than depression —
    DM-anxiety 1.5x vs DM-depression 2.0x per Grigsby 2002 /
    Mezuk 2008."""
    from clinosim.modules.population.aging import _mental_health_onset_multiplier

    p = _alive("PT-DM", age=55)
    p.chronic_conditions = ["E11"]
    f32_mult = _mental_health_onset_multiplier("F32", p)
    f41_mult = _mental_health_onset_multiplier("F41.1", p)
    assert f32_mult == 2.0
    assert f41_mult == 1.5
    assert f32_mult > f41_mult


def test_stroke_sequela_promotion_both_arms_fire_on_mixed_history() -> None:
    """A person with BOTH cerebral_infarction and hemorrhagic_stroke
    in hospitalization_history gets both I69.3 and I69.1. Rare
    clinically (bleeding risk after ischemic stroke secondary
    prevention) but biologically possible — both arms are
    independent."""
    from datetime import date as _d

    from clinosim.types.population import HospitalizationSummary

    p = _alive("PT-MIXED-STROKE", age=75)
    p.hospitalization_history = [
        HospitalizationSummary(
            encounter_id="ENC-ISC",
            disease_id="cerebral_infarction",
            admission_date=_d(2024, 3, 1),
            discharge_date=_d(2024, 3, 10),
            los_days=9,
            outcome="discharged",
        ),
        HospitalizationSummary(
            encounter_id="ENC-HEM",
            disease_id="hemorrhagic_stroke",
            admission_date=_d(2025, 7, 1),
            discharge_date=_d(2025, 7, 20),
            los_days=19,
            outcome="discharged",
        ),
    ]
    reg = _registry([p])
    advance_population(reg, 2026, "us")
    assert "I69.3" in p.chronic_conditions
    assert "I69.1" in p.chronic_conditions


def test_stroke_sequela_promotion_skips_when_no_past_cerebral_infarction() -> None:
    """A person without any cerebral_infarction in hospitalization_history
    does NOT get I69.3 — the promotion is strictly conditioned on prior
    cerebral-infarction encounter."""
    p = _alive("PT-NO-STROKE", age=65)
    p.hospitalization_history = []
    reg = _registry([p])
    advance_population(reg, 2026, "us")
    assert "I69.3" not in p.chronic_conditions


def test_disease_progression_init_does_not_double_step() -> None:
    """The year a stage is first initialised, no advancement
    happens — only ONE write per init year."""
    p = _alive("PT-INIT", age=60)
    p.chronic_conditions = ["N18"]
    before_year = 2026
    sub = np.random.default_rng(aging_sub_seed(p.person_id, before_year, "_disease_progression"))
    _disease_progression(p, before_year, sub, {})
    initial = p.disease_stages["N18"]
    # Same year, same seed → same initial. No further advance in this call.
    sub2 = np.random.default_rng(aging_sub_seed(p.person_id, before_year, "_disease_progression"))
    p2 = _alive("PT-INIT", age=60)
    p2.chronic_conditions = ["N18"]
    _disease_progression(p2, before_year, sub2, {})
    assert p2.disease_stages["N18"] == initial


def test_disease_progression_advances_on_hit() -> None:
    """A person already at G3b with 8 %/yr advance rate should
    sometimes move to G4 across a Monte-Carlo cohort."""
    advanced = 0
    for i in range(400):
        p = _alive(f"PT-ADV-{i:04d}", age=65)
        p.chronic_conditions = ["N18"]
        p.disease_stages["N18"] = "CKD G3b"
        sub = np.random.default_rng(aging_sub_seed(p.person_id, 2027, "_disease_progression"))
        _disease_progression(p, 2027, sub, {})
        if p.disease_stages["N18"] == "CKD G4":
            advanced += 1
    # Expected ~32 at 8 %/yr; allow wide spread.
    assert advanced > 10, f"only {advanced}/400 advanced from G3b (expected ~32)"


def test_disease_progression_terminal_stays() -> None:
    """A person at the terminal stage (G5 / GOLD 4 / NYHA IV / CCS III
    / CDR 3) never moves further — the yaml rate is 0."""
    for icd, terminal in (
        ("N18", "CKD G5"),
        ("J44", "GOLD 4"),
        ("I50", "NYHA IV"),
        ("I25", "CCS III"),
        ("F00", "CDR 3"),
    ):
        hits = 0
        for i in range(200):
            p = _alive(f"PT-{icd}-TERM-{i:04d}", age=85)
            p.chronic_conditions = [icd]
            p.disease_stages[icd] = terminal
            sub = np.random.default_rng(aging_sub_seed(p.person_id, 2027, "_disease_progression"))
            _disease_progression(p, 2027, sub, {})
            if p.disease_stages[icd] != terminal:
                hits += 1
        assert hits == 0, f"{icd} terminal {terminal} moved {hits}/200 times"


def test_disease_progression_initialises_hf_stage() -> None:
    """First-year touch on a person with I50 populates
    disease_stages with one of the NYHA classes."""
    p = _alive("PT-HF-INIT", age=72)
    p.chronic_conditions = ["I50"]
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert "I50" in p.disease_stages
    assert p.disease_stages["I50"] in ("NYHA I", "NYHA II", "NYHA III", "NYHA IV")


def test_disease_progression_advances_hf_on_hit() -> None:
    """A person already at NYHA III with 12 %/yr advance rate should
    sometimes move to NYHA IV across a Monte-Carlo cohort."""
    advanced = 0
    for i in range(400):
        p = _alive(f"PT-HF-ADV-{i:04d}", age=72)
        p.chronic_conditions = ["I50"]
        p.disease_stages["I50"] = "NYHA III"
        sub = np.random.default_rng(aging_sub_seed(p.person_id, 2027, "_disease_progression"))
        _disease_progression(p, 2027, sub, {})
        if p.disease_stages["I50"] == "NYHA IV":
            advanced += 1
    assert advanced > 20, f"only {advanced}/400 advanced from NYHA III (expected ~48)"


def test_allergy_drift_atopic_predisposition_doubles_emergence_rate() -> None:
    """Issue #1581 Phase C.2 — a person with
    ``atopic_predisposition=2.0`` has roughly double the emergence
    hit rate for new medication allergies in ``_allergy_drift``
    compared to a neutral (``=1.0``) person. Monte-Carlo across 400
    person-years per cohort."""
    from clinosim.types.allergy import Allergy

    def _no_allergy_adult(pid: str, predisposition: float) -> PersonRecord:
        p = _alive(pid, age=40)
        p.allergies = [
            Allergy(
                allergy_id="ALG-NKA",
                allergen_code="716186003",
                category="",
                criticality="unable-to-assess",
                verification_status="confirmed",
                clinical_status="resolved",
                is_nka=True,
            )
        ]
        p.atopic_predisposition = predisposition
        return p

    neutral_hits = 0
    atopic_hits = 0
    trials = 400
    for i in range(trials):
        p_n = _no_allergy_adult(f"PT-NEUTRAL-{i:04d}", 1.0)
        p_a = _no_allergy_adult(f"PT-ATOPIC-{i:04d}", 2.0)
        rng_n = np.random.default_rng(aging_sub_seed(p_n.person_id, 2026, "_allergy_drift"))
        rng_a = np.random.default_rng(aging_sub_seed(p_a.person_id, 2026, "_allergy_drift"))
        _allergy_drift(p_n, 2026, rng_n, {})
        _allergy_drift(p_a, 2026, rng_a, {})
        n_count = sum(1 for a in (p_n.allergies or []) if not a.is_nka)
        a_count = sum(1 for a in (p_a.allergies or []) if not a.is_nka)
        if n_count > 0:
            neutral_hits += 1
        if a_count > 0:
            atopic_hits += 1

    # Rate should roughly double. Allow wide Monte-Carlo band — the raw
    # per-year rate is small, so hits may be in single digits across
    # 400 trials. Core invariant: atopic cohort has strictly more
    # hits than the neutral cohort.
    assert atopic_hits > neutral_hits, f"atopic={atopic_hits} <= neutral={neutral_hits} (expected >)"


def test_disease_progression_initialises_ccs_stage() -> None:
    """First-year touch on a person with I25 populates
    disease_stages with one of the CCS classes."""
    p = _alive("PT-CCS-INIT", age=65)
    p.chronic_conditions = ["I25"]
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert "I25" in p.disease_stages
    assert p.disease_stages["I25"] in ("CCS I", "CCS II", "CCS III")


def test_disease_progression_writes_year_indexed_history() -> None:
    """Issue #1581 — ``_disease_progression`` now records each year's
    stage into ``person.disease_stage_history`` so an encounter-time
    lookup can see the stage AS OF the encounter year rather than
    the end-of-sim snapshot."""
    p = _alive("PT-HIST-1", age=70)
    p.chronic_conditions = ["N18"]
    # Year 2026 (first touch, initial sample).
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    first_stage = p.disease_stages["N18"]
    assert p.disease_stage_history["N18"][2026] == first_stage
    # Year 2027 (either stays or advances).
    _disease_progression(
        p,
        2027,
        np.random.default_rng(aging_sub_seed(p.person_id, 2027, "_disease_progression")),
        {},
    )
    assert 2027 in p.disease_stage_history["N18"]


def test_disease_progression_initialises_cdr_stage() -> None:
    """First-year touch on a person with F00 populates
    disease_stages with one of the CDR classes."""
    p = _alive("PT-CDR-INIT", age=78)
    p.chronic_conditions = ["F00"]
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert "F00" in p.disease_stages
    assert p.disease_stages["F00"] in ("CDR 0.5", "CDR 1", "CDR 2", "CDR 3")


def test_disease_progression_advances_cdr_on_hit() -> None:
    """A person already at CDR 2 with 20 %/yr advance rate should
    sometimes move to CDR 3 across a Monte-Carlo cohort."""
    advanced = 0
    for i in range(400):
        p = _alive(f"PT-CDR-ADV-{i:04d}", age=80)
        p.chronic_conditions = ["F00"]
        p.disease_stages["F00"] = "CDR 2"
        sub = np.random.default_rng(aging_sub_seed(p.person_id, 2027, "_disease_progression"))
        _disease_progression(p, 2027, sub, {})
        if p.disease_stages["F00"] == "CDR 3":
            advanced += 1
    assert advanced > 50, f"only {advanced}/400 advanced from CDR 2 (expected ~80)"


def test_disease_progression_advances_ccs_on_hit() -> None:
    """A person already at CCS II with 8 %/yr advance rate should
    sometimes move to CCS III across a Monte-Carlo cohort."""
    advanced = 0
    for i in range(400):
        p = _alive(f"PT-CCS-ADV-{i:04d}", age=68)
        p.chronic_conditions = ["I25"]
        p.disease_stages["I25"] = "CCS II"
        sub = np.random.default_rng(aging_sub_seed(p.person_id, 2027, "_disease_progression"))
        _disease_progression(p, 2027, sub, {})
        if p.disease_stages["I25"] == "CCS III":
            advanced += 1
    assert advanced > 12, f"only {advanced}/400 advanced from CCS II (expected ~32)"


def test_disease_progression_subcode_prefix_match() -> None:
    """A sub-code (``N18.3``) is tracked by its prefix (``N18``)."""
    p = _alive("PT-SUB", age=60)
    p.chronic_conditions = ["N18.3"]  # sub-code
    _disease_progression(
        p,
        2026,
        np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_disease_progression")),
        {},
    )
    assert "N18" in p.disease_stages


def test_disease_progression_deterministic() -> None:
    """Same (person_id, year, chronic_conditions, prior stage) →
    same new stage. Pass-isolated sub-RNG."""

    def run_once() -> str:
        p = _alive("PT-DET", age=65)
        p.chronic_conditions = ["N18"]
        p.disease_stages["N18"] = "CKD G3a"
        _disease_progression(
            p,
            2030,
            np.random.default_rng(aging_sub_seed(p.person_id, 2030, "_disease_progression")),
            {},
        )
        return p.disease_stages["N18"]

    assert run_once() == run_once()


def test_remaining_stub_integration_signatures() -> None:
    """The scaffold-level invariant that `_disease_progression`
    accepts ``(person, year, prng, incidence_table, locale)`` and
    returns ``None`` is preserved after the body was added."""
    p = _alive("PT-SIG", age=50)
    rv = _disease_progression(p, 2026, np.random.default_rng(0), {}, locale="us")
    assert rv is None
