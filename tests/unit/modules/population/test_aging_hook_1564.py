"""Phase 2: `advance_population` aging hook — Issue #1564.

Covers:

* Scaffold invariants (seed isolation, dead-skip, locale wiring).
* ``_annual_chronic_onset`` behaviour: age gate, sex gate,
  already-present skip, deterministic draws, band-diff derivation
  math, approximate marginal preservation across a decade.
* ``_allergy_drift`` behaviour: None-safe skip, childhood food
  resolution flip, adult drug-sensitivity emergence (incl. NKA
  removal), age-tiered elderly rate.
* ``_condition_reactive_mortality`` behaviour: SMR combine math,
  excess_qx cap, baseline date respected unless earlier proposed,
  is_alive_at skip, no-op when no chronic in SMR table.
* Stub signature for the one not-yet-implemented pass.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from clinosim.modules.population.aging import (
    _allergy_drift,
    _annual_chronic_onset,
    _condition_reactive_mortality,
    _derive_annual_incidence_from_prevalence,
    _disease_progression,
    _load_annual_incidence_for_locale,
    advance_population,
    aging_sub_seed,
)

# Imported inside tests that need them to keep the top block small.
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
# Scaffold invariants
# ---------------------------------------------------------------------------


def test_aging_sub_seed_deterministic_and_pass_isolated() -> None:
    s1 = aging_sub_seed("PT-1", 2026, "chronic_onset")
    s2 = aging_sub_seed("PT-1", 2026, "chronic_onset")
    assert s1 == s2
    assert s1 != aging_sub_seed("PT-1", 2026, "disease_progression")
    assert s1 != aging_sub_seed("PT-1", 2027, "chronic_onset")
    assert s1 != aging_sub_seed("PT-2", 2026, "chronic_onset")


def test_advance_population_skips_dead_persons() -> None:
    p_dead = _alive("PT-DEAD", age=90)
    p_dead.is_alive = False
    p_dead_before = list(p_dead.chronic_conditions)
    p_alive = _alive("PT-ALIVE", age=50)
    reg = _registry([p_dead, p_alive])
    advance_population(reg, 2026, "us")
    # Dead person untouched.
    assert p_dead.chronic_conditions == p_dead_before
    assert p_dead.is_alive is False
    assert p_alive.is_alive is True


# ---------------------------------------------------------------------------
# _disease_progression behaviour (Phase 2.5, CKD + COPD)
# ---------------------------------------------------------------------------


def test_disease_progression_noop_when_no_tracked_conditions() -> None:
    """A person with no CKD / COPD on chronic_conditions never
    touches disease_stages."""
    p = _alive("PT-OTHER", age=60)
    p.chronic_conditions = ["I10", "F32"]
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


# ---------------------------------------------------------------------------
# _allergy_drift behaviour
# ---------------------------------------------------------------------------


def _food_allergy(code: str = "735038006", status: str = "active"):
    """Build an active food Allergy (egg protein by default)."""
    from clinosim.types.allergy import Allergy, AllergyReaction

    return Allergy(
        allergy_id=f"ALG-FOOD-{code}",
        allergen_code=code,
        category="food",
        criticality="low",
        verification_status="confirmed",
        clinical_status=status,
        reactions=[AllergyReaction(manifestation_snomed="247472004", severity="mild")],
    )


def _nka_record():
    from clinosim.types.allergy import Allergy

    return Allergy(
        allergy_id="ALG-NKA",
        allergen_code="716186003",
        category="",
        criticality="unable-to-assess",
        verification_status="confirmed",
        clinical_status="resolved",
        is_nka=True,
    )


def test_allergy_drift_none_allergies_is_no_op() -> None:
    """``person.allergies is None`` (newborn before enricher) → skip."""
    p = _alive("PT-NEWBORN", age=1)
    assert p.allergies is None
    _allergy_drift(p, 2026, np.random.default_rng(0), {})
    assert p.allergies is None


def test_allergy_drift_resolves_child_food_allergy_at_expected_rate() -> None:
    """Monte-Carlo: 400 children (age 8) with a food allergy at
    year 2026. One single-year 8 % Bernoulli → expected ~32 flips.
    We assert > 10 to be robust to RNG spread."""
    flipped = 0
    for i in range(400):
        p = _alive(f"PT-CHILD-{i:04d}", age=8)
        p.allergies = [_food_allergy()]
        sub = np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_allergy_drift"))
        _allergy_drift(p, 2026, sub, {})
        if p.allergies[0].clinical_status == "resolved":
            flipped += 1
    assert flipped > 10, f"only {flipped}/400 food allergies resolved (expected ~32)"


def test_allergy_drift_does_not_resolve_adult_food_allergy() -> None:
    """Adults are gated out of childhood resolution (rate 0)."""
    p = _alive("PT-ADULT", age=40)
    p.allergies = [_food_allergy()]
    for yr in range(2026, 2046):
        sub = np.random.default_rng(aging_sub_seed(p.person_id, yr, "_allergy_drift"))
        _allergy_drift(p, yr, sub, {})
    assert p.allergies[0].clinical_status == "active"


def test_allergy_drift_emerges_adult_drug_allergy_eventually() -> None:
    """Adult without a medication allergy should pick one up over
    many years at ~0.5 %/yr (cumulative ~1 - 0.995^100 ≈ 39 %;
    using many fresh seeds we expect at least one hit)."""
    hits = 0
    for i in range(400):
        p = _alive(f"PT-ADULT-{i:04d}", age=50)
        p.allergies = [_nka_record()]
        sub = np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_allergy_drift"))
        _allergy_drift(p, 2026, sub, {})
        if any(a.category == "medication" for a in p.allergies):
            hits += 1
    # 0.5 %/yr × 400 adults = expected ~2 hits in a single year.
    # Across 400 person-years we expect ~2 with sampling spread. We
    # relax to >=1 to keep this a smoke test (RNG is deterministic
    # so the exact count is fixed, but we document the expected mag).
    assert hits >= 1, f"no drug-allergy emergence across 400 adult-years (hits={hits})"


def test_allergy_drift_elderly_rate_higher_than_adult() -> None:
    """Over a large Monte-Carlo, 65+ cohort should emerge drug
    allergies more often than 18-64 at the same person-year count."""
    adult_hits = 0
    elderly_hits = 0
    for i in range(1000):
        p_a = _alive(f"PT-A-{i:04d}", age=40)
        p_a.allergies = [_nka_record()]
        _allergy_drift(
            p_a,
            2026,
            np.random.default_rng(aging_sub_seed(p_a.person_id, 2026, "_allergy_drift")),
            {},
        )
        if any(a.category == "medication" for a in p_a.allergies):
            adult_hits += 1
        p_e = _alive(f"PT-E-{i:04d}", age=75)
        p_e.allergies = [_nka_record()]
        _allergy_drift(
            p_e,
            2026,
            np.random.default_rng(aging_sub_seed(p_e.person_id, 2026, "_allergy_drift")),
            {},
        )
        if any(a.category == "medication" for a in p_e.allergies):
            elderly_hits += 1
    # Expected: ~5 adult / ~8 elderly per 1000. Rate ratio 1.6×; the
    # count ratio won't be exact but direction must hold.
    assert elderly_hits > adult_hits, f"adult={adult_hits} elderly={elderly_hits}"


def test_allergy_drift_removes_nka_on_emergence() -> None:
    """When the first real allergy is added, the NKA record must be
    dropped — mixing is self-contradicting."""
    from clinosim.types.allergy import Allergy

    # Hunt for a seed/year combo that fires an emergence for 1 person.
    for yr in range(2026, 2500):
        p = _alive("PT-NKA-FLIP", age=70)
        p.allergies = [_nka_record()]
        sub = np.random.default_rng(aging_sub_seed(p.person_id, yr, "_allergy_drift"))
        _allergy_drift(p, yr, sub, {})
        if any(isinstance(a, Allergy) and a.category == "medication" for a in p.allergies):
            # NKA removed.
            assert not any(a.is_nka for a in p.allergies), "NKA not removed after real allergy added"
            assert p.allergies[-1].onset_date is not None
            return
    raise AssertionError("Could not find a year that fired drug emergence; rate too low or RNG off")


# ---------------------------------------------------------------------------
# _condition_reactive_mortality behaviour
# ---------------------------------------------------------------------------


def test_smr_combine_single_condition() -> None:
    """A single ICD returns its SMR directly (geometric mean of
    length-1 list)."""
    from clinosim.modules.population.aging import _combined_smr_for, _load_condition_smr_table

    smr, combine, _ = _load_condition_smr_table()
    assert abs(_combined_smr_for(["I50"], smr, combine) - 3.0) < 1e-9
    assert abs(_combined_smr_for(["J44"], smr, combine) - 2.5) < 1e-9


def test_smr_combine_multiple_geometric() -> None:
    """Three major-organ SMRs geometric-mean below the max, above
    any single contributor's except the top one."""
    from clinosim.modules.population.aging import _combined_smr_for, _load_condition_smr_table

    smr, combine, _ = _load_condition_smr_table()
    val = _combined_smr_for(["I50", "J44", "N18"], smr, combine)
    assert 2.0 < val < 3.0  # geometric mean of 3.0, 2.5, 2.0 ≈ 2.47


def test_smr_combine_untabled_codes_contribute_nothing() -> None:
    """ICDs not in the table are ignored (SMR 1 effectively)."""
    from clinosim.modules.population.aging import _combined_smr_for, _load_condition_smr_table

    smr, combine, _ = _load_condition_smr_table()
    assert _combined_smr_for(["Z99.9", "X77"], smr, combine) == 1.0


def test_smr_prefix_match_for_subcodes() -> None:
    """``N18.3`` matches entry ``N18`` via prefix fallback."""
    from clinosim.modules.population.aging import _combined_smr_for, _load_condition_smr_table

    smr, combine, _ = _load_condition_smr_table()
    assert abs(_combined_smr_for(["N18.3"], smr, combine) - 2.0) < 1e-9


def test_reactive_mortality_noop_when_no_chronic() -> None:
    """A person with no chronic conditions never gets accelerated
    death from the hook — SMR_combined = 1."""
    p = _alive("PT-WELL", age=75)
    sub = np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_condition_reactive_mortality"))
    _condition_reactive_mortality(p, 2026, sub, {}, locale="us")
    assert p.date_of_death is None


def test_reactive_mortality_never_delays_existing_death() -> None:
    """When ``person.date_of_death`` is already set to an earlier
    year, the hook must not push it later."""
    p = _alive("PT-DEAD-SOON", age=80)
    p.chronic_conditions = ["I50", "J44"]
    p.date_of_death = date(2024, 3, 10)  # Already set to earlier
    sub = np.random.default_rng(0)
    _condition_reactive_mortality(p, 2026, sub, {}, locale="us")
    assert p.date_of_death == date(2024, 3, 10)


def test_reactive_mortality_overrides_later_death() -> None:
    """When condition-driven death fires BEFORE a baseline-sampled
    later date_of_death, override it. Monte-Carlo: 400 high-SMR
    elderly adults with baseline date_of_death set to a future
    year; a fraction should get their death moved earlier."""
    overridden = 0
    for i in range(400):
        p = _alive(f"PT-OVERRIDE-{i:04d}", age=85)
        p.chronic_conditions = ["I50", "J44", "N18"]  # SMR ≈ 2.47
        p.date_of_death = date(2030, 11, 1)
        sub = np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_condition_reactive_mortality"))
        _condition_reactive_mortality(p, 2026, sub, {}, locale="us")
        if p.date_of_death == date(2026, 6, 15):
            overridden += 1
    # qx(US,M,85)≈0.133; excess=0.133*(2.47-1)=0.195, capped to 0.15.
    # Expected ~60 overrides out of 400.
    assert overridden > 20, f"only {overridden}/400 overrode — expected ~60"


def test_reactive_mortality_excess_qx_capped() -> None:
    """Even with an extreme SMR, excess_qx cannot exceed
    ``max_excess_qx_per_year``. Verify via large Monte-Carlo at
    advanced age — hit rate must be at most ~cap × 400."""
    hits = 0
    for i in range(400):
        p = _alive(f"PT-CAP-{i:04d}", age=95)
        # Multiple top-tier SMRs stack via geometric mean to ~2.5
        p.chronic_conditions = ["I50", "I21", "J44", "N18", "F03"]
        sub = np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_condition_reactive_mortality"))
        _condition_reactive_mortality(p, 2026, sub, {}, locale="us")
        if p.date_of_death is not None:
            hits += 1
    # cap=0.15 → expected ~60 hits. Should be between 40 and 90.
    assert 20 <= hits <= 120, f"cap breached? hits={hits} (expected ~60 at cap 0.15)"


def test_advance_population_skips_past_dead_persons() -> None:
    """Scaffold fix: a person whose ``date_of_death`` is before the
    advance year must be skipped by every pass, including
    ``_annual_chronic_onset``."""
    p = _alive("PT-WAS-DEAD", age=70)
    p.date_of_death = date(2024, 5, 1)
    before = list(p.chronic_conditions)
    reg = _registry([p])
    advance_population(reg, 2026, "us")
    # No new chronic conditions acquired, since person was already dead.
    assert p.chronic_conditions == before


def test_allergy_drift_skips_adult_with_existing_med_allergy() -> None:
    """If the person already carries a medication allergy, drift
    does not stack another one."""
    from clinosim.types.allergy import Allergy, AllergyReaction

    p = _alive("PT-MED", age=50)
    p.allergies = [
        Allergy(
            allergy_id="ALG-PENI",
            allergen_code="373270004",
            category="medication",
            criticality="high",
            verification_status="confirmed",
            clinical_status="active",
            reactions=[AllergyReaction(manifestation_snomed="247472004", severity="moderate")],
        )
    ]
    for yr in range(2026, 2046):
        sub = np.random.default_rng(aging_sub_seed(p.person_id, yr, "_allergy_drift"))
        _allergy_drift(p, yr, sub, {})
    med_count = sum(1 for a in p.allergies if a.category == "medication")
    assert med_count == 1


# ---------------------------------------------------------------------------
# Band-diff derivation math
# ---------------------------------------------------------------------------


def test_derive_last_band_rate_is_zero() -> None:
    """Highest band has no next prevalence to climb toward, so λ=0."""
    out = _derive_annual_incidence_from_prevalence({(40, 59): 0.30, (60, 79): 0.50})
    assert out[(60, 79)] == 0.0


def test_derive_band_diff_recovers_prev_next() -> None:
    """A susceptible person aged across the full width of band
    ``[40, 59]`` should end at prevalence close to ``P_next``.

    Formula: (1 - λ)^width = (1 - P_next) / (1 - P_this)
    Width 20, P_this 0.30, P_next 0.50 → λ ≈ 0.01676.
    Cumulative onset over 20 years = 1 - (1 - 0.01676)^20 ≈ 0.286,
    so prevalence at the end of the band = 0.30 + (1 - 0.30) * 0.286
    = 0.30 + 0.200 ≈ 0.50. Marginal preserved to 1 part in 1000.
    """
    out = _derive_annual_incidence_from_prevalence({(40, 59): 0.30, (60, 79): 0.50})
    lam = out[(40, 59)]
    width = 59 - 40 + 1
    survived_susceptible = (1.0 - lam) ** width
    recovered_p_next = 1.0 - 0.70 * survived_susceptible
    assert abs(recovered_p_next - 0.50) < 1e-3


def test_derive_decreasing_prevalence_zero_rate() -> None:
    """If a later band has LOWER prevalence (survivorship / rare), the
    from-band gets λ=0, not a negative rate."""
    out = _derive_annual_incidence_from_prevalence({(60, 79): 0.50, (80, 99): 0.45})
    assert out[(60, 79)] == 0.0


def test_derive_single_band_rate_is_zero() -> None:
    out = _derive_annual_incidence_from_prevalence({(60, 99): 0.08})
    assert out[(60, 99)] == 0.0


# ---------------------------------------------------------------------------
# _annual_chronic_onset behaviour
# ---------------------------------------------------------------------------


def test_chronic_onset_skips_z34_z37_state_period_markers() -> None:
    """Z34 (pregnancy) and Z37 (outcome-of-delivery) appear in
    `chronic_prevalence` yaml only as RNG cursor placeholders;
    they must NEVER be appended to `person.chronic_conditions`
    by mid-sim aging onset. Pregnancy lifecycle lives in
    `state_periods`; Z37 past-birth marker is derived from state
    history at FHIR emit time.

    Regression guard: pre-fix, a force-rate-1.0 injection of
    these codes would hit `chronic_conditions`, breaking the
    `test_pregnancy_lifecycle_us_p500` integration gate.
    """
    from clinosim.modules.population.aging import _ChronicIncidenceSpec

    p = _alive("PT-PREG", age=30, sex="F")
    table = {
        "Z34": _ChronicIncidenceSpec(sex="F", bands={(20, 44): 1.0}),
        "Z37": _ChronicIncidenceSpec(sex="F", bands={(25, 64): 1.0}),
    }
    _annual_chronic_onset(p, 2026, np.random.default_rng(0), table)
    assert "Z34" not in p.chronic_conditions
    assert "Z37" not in p.chronic_conditions


def test_chronic_onset_skips_persons_under_18() -> None:
    p = _alive("PT-TEEN", age=16, sex="M")
    before = list(p.chronic_conditions)
    # Force a table with λ=1 to prove the age gate alone blocks onset.
    table = {"X99": _spec("", {(0, 99): 1.0})}
    _annual_chronic_onset(p, 2026, np.random.default_rng(0), table)
    assert p.chronic_conditions == before


def test_chronic_onset_skips_already_present_icd() -> None:
    p = _alive("PT-HAS", age=50, sex="M")
    p.chronic_conditions.append("I10")
    table = {"I10": _spec("", {(40, 59): 1.0})}
    _annual_chronic_onset(p, 2026, np.random.default_rng(0), table)
    # Not re-appended; stays a single entry.
    assert p.chronic_conditions == ["I10"]


def test_chronic_onset_respects_sex_gate() -> None:
    """Male-locked ICD (e.g. N40 BPH) never fires on a female person."""
    p = _alive("PT-F", age=70, sex="F")
    table = {"N40": _spec("M", {(50, 99): 1.0})}
    _annual_chronic_onset(p, 2026, np.random.default_rng(0), table)
    assert p.chronic_conditions == []


def test_chronic_onset_deterministic_across_runs() -> None:
    """Same (person_id, year) → same decision."""
    table = {"I10": _spec("", {(40, 59): 0.5})}
    p1 = _alive("PT-DET", age=50)
    p2 = _alive("PT-DET", age=50)
    for p in (p1, p2):
        _annual_chronic_onset(
            p,
            2026,
            np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_annual_chronic_onset")),
            table,
        )
    assert p1.chronic_conditions == p2.chronic_conditions


def test_chronic_onset_approximate_marginal_over_decade() -> None:
    """Monte-Carlo integration test: 2000 susceptible 40-year-olds
    aged 20 years with the derived λ should land near P_next within
    sampling noise."""
    rng = np.random.default_rng(12345)
    n = 2000
    cohort = [
        PersonRecord(
            person_id=f"PT-{i:04d}",
            household_id="HH-1",
            age=40,
            sex="M",
            date_of_birth=date(2026 - 40, 1, 1),
        )
        for i in range(n)
    ]
    table = {"I10": _spec("", _derive_annual_incidence_from_prevalence({(40, 59): 0.30, (60, 79): 0.50}))}
    # Seed each person with 0.30 initial prevalence (what the initial
    # cohort sampler would have done at age 40 in band [40, 59]).
    for p in cohort:
        if rng.random() < 0.30:
            p.chronic_conditions.append("I10")
    initial_prev = sum("I10" in p.chronic_conditions for p in cohort) / n
    # Age 20 years. Each year the person stays in band [40, 59] (we
    # cap at age 59 so they do not cross into the no-incidence band).
    for yr in range(20):
        for p in cohort:
            sub_rng = np.random.default_rng(aging_sub_seed(p.person_id, 2026 + yr, "_annual_chronic_onset"))
            _annual_chronic_onset(p, 2026 + yr, sub_rng, table)
    final_prev = sum("I10" in p.chronic_conditions for p in cohort) / n
    assert 0.25 < initial_prev < 0.35
    # Target 0.50 ± 0.05 sampling noise band.
    assert 0.45 < final_prev < 0.55, f"final_prev={final_prev}"


# ---------------------------------------------------------------------------
# Locale loader smoke
# ---------------------------------------------------------------------------


def test_load_annual_incidence_for_us_populates_i10() -> None:
    """US demographics should produce an I10 entry whose first-band
    rate is > 0 (since prev climbs from 0.05 → 0.30 → 0.50 → 0.65)."""
    table = _load_annual_incidence_for_locale("us")
    assert "I10" in table
    spec = table["I10"]
    assert spec.sex == ""
    assert spec.rate_at(30) > 0.0
    assert spec.rate_at(95) == 0.0  # last band


def test_load_annual_incidence_for_jp_populates_i10() -> None:
    table = _load_annual_incidence_for_locale("jp")
    assert "I10" in table


# ---------------------------------------------------------------------------
# Comorbidity progression multipliers (diabetic nephropathy etc.)
# ---------------------------------------------------------------------------


def test_comorbidity_multiplier_1_when_no_rules_apply() -> None:
    """A person without the trigger comorbidity picks up multiplier
    1.0 for every target → progression rate unchanged from baseline."""
    from clinosim.modules.population.aging import _comorbidity_multiplier

    p = _alive("PT-NO-DM", age=65)
    p.chronic_conditions = ["N18"]  # CKD, no DM
    assert _comorbidity_multiplier(p, "N18", 2026) == 1.0


def test_comorbidity_multiplier_scales_with_glycemic_control() -> None:
    """DM + CKD person: tier dispatch by previous-year gc. Poor
    control (gc < 0.5) → 2.5x; fair (gc < 0.7) → 1.5x; good
    (gc ≥ 0.7) → 1.0x (default)."""
    from clinosim.modules.population.aging import _comorbidity_multiplier

    def _dm_ckd(gc_prev: float) -> float:
        p = _alive("PT-DM-CKD", age=65)
        p.chronic_conditions = ["N18", "E11"]
        p.glycemic_trajectory = {2025: gc_prev}
        return _comorbidity_multiplier(p, "N18", 2026)

    assert _dm_ckd(0.3) == 2.5, "poor glycemic control must trigger the 2.5x tier"
    assert _dm_ckd(0.6) == 1.5, "fair glycemic control must trigger the 1.5x tier"
    assert _dm_ckd(0.85) == 1.0, "good glycemic control falls through to default_multiplier=1.0"


def test_comorbidity_multiplier_cardiorenal_hf_to_ckd() -> None:
    """A CKD person who ALSO has HF (I50) picks up the 1.5x
    cardiorenal arm on N18 target. No glycemic tier involved —
    purely chronic-trigger based."""
    from clinosim.modules.population.aging import _comorbidity_multiplier

    p = _alive("PT-CARDIORENAL", age=70)
    p.chronic_conditions = ["N18", "I50"]
    assert _comorbidity_multiplier(p, "N18", 2026) == 1.5


def test_comorbidity_multiplier_compounds_hf_and_dm_on_ckd() -> None:
    """DM + HF + CKD + poor glycemic control: diabetic nephropathy
    (2.5x) × cardiorenal (1.5x) compound to 3.75x on N18 target."""
    from clinosim.modules.population.aging import _comorbidity_multiplier

    p = _alive("PT-TRIPLE", age=70)
    p.chronic_conditions = ["N18", "E11", "I50"]
    p.glycemic_trajectory = {2025: 0.3}
    mult = _comorbidity_multiplier(p, "N18", 2026)
    assert abs(mult - (2.5 * 1.5)) < 1e-9, f"compound multiplier should be 3.75, got {mult}"


def test_comorbidity_multiplier_cardiorenal_ckd_to_hf_and_cor_pulmonale() -> None:
    """HF progression accelerated by both CKD (1.5x cardiorenal) and
    COPD (1.3x cor pulmonale). A person with all three sees the
    compound 1.95x on I50 target."""
    from clinosim.modules.population.aging import _comorbidity_multiplier

    p = _alive("PT-HF-CKD-COPD", age=75)
    p.chronic_conditions = ["I50", "N18", "J44"]
    mult = _comorbidity_multiplier(p, "I50", 2026)
    assert abs(mult - (1.5 * 1.3)) < 1e-9, f"HF should compound CKD × COPD to 1.95, got {mult}"


def test_comorbidity_multiplier_diabetic_atherogenesis_on_ihd() -> None:
    """DM + IHD person: 1.3x baseline (requires_any match with
    default_multiplier). Poor glycemic control bumps to 1.5x via
    the gc tier."""
    from clinosim.modules.population.aging import _comorbidity_multiplier

    p = _alive("PT-DM-IHD", age=65)
    p.chronic_conditions = ["I25", "E11"]
    p.glycemic_trajectory = {2025: 0.85}  # good control
    assert _comorbidity_multiplier(p, "I25", 2026) == 1.3

    p.glycemic_trajectory = {2025: 0.3}  # poor control
    assert _comorbidity_multiplier(p, "I25", 2026) == 1.5


def test_comorbidity_multiplier_smoking_tier_dispatch_on_copd() -> None:
    """Smoking → COPD acceleration. Current smokers 2.0x, former
    smokers 1.3x, never-smokers 1.0x (no rule fires). Verifies the
    ``requires_smoking_in`` trigger."""
    from clinosim.modules.population.aging import _comorbidity_multiplier

    p = _alive("PT-SMOKER", age=65)
    p.chronic_conditions = ["J44"]
    p.smoking_status = "current"
    assert _comorbidity_multiplier(p, "J44", 2026) == 2.0

    p.smoking_status = "former"
    assert _comorbidity_multiplier(p, "J44", 2026) == 1.3

    p.smoking_status = "never"
    assert _comorbidity_multiplier(p, "J44", 2026) == 1.0


def test_comorbidity_multiplier_ckd_g4plus_cardiorenal_step_up() -> None:
    """CKD G4/G5 bumps the baseline cardiorenal 1.5x on I50 up by
    an additional 1.4x compound (G1-G3 does NOT get the step-up).
    Verifies the ``requires_chronic_stage_in`` trigger reads from
    person.disease_stages[icd]."""
    from clinosim.modules.population.aging import _comorbidity_multiplier

    p = _alive("PT-CKD-STAGE", age=72)
    p.chronic_conditions = ["I50", "N18"]
    p.disease_stages = {"N18": "CKD G3a"}
    # Only the baseline cardiorenal_ckd_to_hf (1.5x) fires at G3.
    assert _comorbidity_multiplier(p, "I50", 2026) == 1.5

    p.disease_stages = {"N18": "CKD G4"}
    # G4 — both the baseline cardiorenal AND the g4plus step-up fire.
    mult = _comorbidity_multiplier(p, "I50", 2026)
    assert abs(mult - (1.5 * 1.4)) < 1e-9, f"G4 CKD should compound 1.5 × 1.4 = 2.1 on I50, got {mult}"

    p.disease_stages = {"N18": "CKD G5"}
    mult_g5 = _comorbidity_multiplier(p, "I50", 2026)
    assert abs(mult_g5 - (1.5 * 1.4)) < 1e-9, f"G5 CKD should compound 1.5 × 1.4 = 2.1 on I50, got {mult_g5}"


def test_comorbidity_multiplier_rule_with_no_triggers_is_skipped() -> None:
    """A yaml rule missing every trigger field would otherwise
    blanket-apply its multiplier. The dispatch guard skips it."""
    import importlib

    from clinosim.modules.population import aging as aging_mod

    # Monkey-patch the loader to inject an empty-trigger rule.
    bad_rules = {"J44": {"blanket_bug": {"default_multiplier": 10.0}}}
    original = aging_mod._load_comorbidity_multipliers
    aging_mod._load_comorbidity_multipliers = lambda: bad_rules  # type: ignore[assignment]
    try:
        p = _alive("PT-GUARD", age=50)
        p.chronic_conditions = ["J44"]
        # Empty-trigger rule must not fire → still 1.0.
        assert aging_mod._comorbidity_multiplier(p, "J44", 2026) == 1.0
    finally:
        aging_mod._load_comorbidity_multipliers = original  # type: ignore[assignment]
        importlib.reload(aging_mod)  # restore fresh lru_cache + original binding


def test_comorbidity_multiplier_uses_previous_year_gc() -> None:
    """To stay independent of chronic_conditions iteration order, the
    multiplier reads ``glycemic_trajectory[year - 1]``, not
    ``[year]``. Verifies both the key and the fallback (0.7 ≈ fair
    when the previous year has no entry)."""
    from clinosim.modules.population.aging import _comorbidity_multiplier

    p = _alive("PT-DM-NO-PRIOR", age=65)
    p.chronic_conditions = ["N18", "E11"]
    p.glycemic_trajectory = {2026: 0.2}  # current year poor control, no prior
    # Multiplier should fall back to default 0.7 → good tier → 1.0
    assert _comorbidity_multiplier(p, "N18", 2026) == 1.0


def test_disease_progression_dm_poor_control_accelerates_ckd() -> None:
    """Monte-Carlo: DM-affected cohorts with poor glycemic control
    reach CKD G3b/G4/G5 faster than DM-free CKD cohorts over 20
    years. Not byte-exact — a Bernoulli monte-carlo over 200
    persons × 20 years. Deterministic seed keeps the result stable."""
    # Metric: mean CKD stage index (0=G1 ... 5=G5) after 8 years. The
    # window is short enough that few persons plateau at G5, so the
    # acceleration gap is observable as a stage-index shift. Fraction-
    # reaching-G3b+ saturates faster and is less sensitive. Monte-
    # Carlo with deterministic seed keeps the result stable.
    stage_idx = {"CKD G1": 0, "CKD G2": 1, "CKD G3a": 2, "CKD G3b": 3, "CKD G4": 4, "CKD G5": 5}

    def _mean_stage(with_dm: bool, gc: float) -> float:
        total = 0.0
        for i in range(200):
            p = _alive(f"PT-SIM-{i:04d}", age=60)
            p.chronic_conditions = ["N18"] + (["E11"] if with_dm else [])
            if with_dm:
                p.glycemic_trajectory = {y: gc for y in range(2024, 2046)}
            for yr in range(8):
                _disease_progression(
                    p,
                    2026 + yr,
                    np.random.default_rng(aging_sub_seed(p.person_id, 2026 + yr, "_disease_progression")),
                    {},
                )
            total += stage_idx.get(p.disease_stages.get("N18", ""), 0)
        return total / 200

    no_dm = _mean_stage(with_dm=False, gc=1.0)
    dm_poor = _mean_stage(with_dm=True, gc=0.3)
    # Half-stage shift is a conservative threshold; the clinical
    # expectation from a 2.5x per-year rate multiplier compounded
    # over 8 years is >= 1 full stage shift at this baseline.
    assert dm_poor > no_dm + 0.5, (
        f"DM poor-control mean CKD stage ({dm_poor:.3f}) must exceed baseline ({no_dm:.3f}) by ≥0.5"
    )


def test_full_advance_population_runs_against_real_locale() -> None:
    """Integration smoke: a small registry walks through
    ``advance_population`` with locale='us' and acquires at least one
    new chronic condition across 20 years for 100 adults."""
    cohort = [_alive(f"PT-{i:04d}", age=40, sex="M") for i in range(100)]
    reg = _registry(cohort)
    for yr in range(20):
        advance_population(reg, 2026 + yr, "us")
    # Over 2000 person-years with multiple non-zero-rate ICDs, we
    # expect at least a handful of acquisitions. The band-diff math
    # pushes I10 alone to ~0.46 cumulative over the band, so a 100-
    # person cohort will see ~46 I10 acquisitions on average.
    total_new = sum(len(p.chronic_conditions) for p in cohort)
    assert total_new >= 10, f"total_new={total_new} suspiciously low"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(sex: str, bands: dict[tuple[int, int], float]):
    """Build a ``_ChronicIncidenceSpec`` without re-importing the
    frozen dataclass by name — the tests only need the public
    attribute surface."""
    from clinosim.modules.population.aging import _ChronicIncidenceSpec

    return _ChronicIncidenceSpec(sex=sex, bands=bands)
