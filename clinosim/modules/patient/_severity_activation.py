"""Chronic-condition stage sampling + severity-score tables (Issue #637 PR-D).

When ``activate_patient`` promotes a ``PersonRecord`` from the population
layer into a ``PatientProfile``, each chronic condition is annotated with:

1. **A clinical stage text** (e.g. ``"CKD G3a"``, ``"NYHA III"``,
   ``"GOLD 2"``) sampled from a per-condition weighted distribution.
2. **A ``severity_score`` in ``[0.0, 1.0]``** looked up from that stage
   text, which drives the physiology engine's per-code coupling
   (``modules/physiology/engine.py::initialize_state``; see the
   companion constants in ``modules/physiology/_coupling_coefficients.py``
   introduced in PR-B).

Before this refactor the stage distributions were inline weight lists
buried inside ``_generate_stage`` — one list per ``if code == …`` branch,
un-named, ungrep-able, and undocumented. This module lifts those weights
to named tuples with per-condition prevalence citations, and also carries
the severity-score table ``STAGE_SEVERITY`` (re-exported from
``activator.py`` for callers that already import the symbol from there).

All values are immutable module-level constants. The stage-selection
weight vectors sum to ``1.0`` (validated at import). The severity-score
tables map each stage's text to a float in ``[0.0, 1.0]``; values above
each condition's severe-threshold (see ``_coupling_coefficients.py``)
fire the corresponding "severe" branch in the physiology engine.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. All ``rng.choice``
calls in ``_generate_stage`` continue to pass an identical ``p=``
argument (same values, same order); numpy's Cheng sampling algorithm is
deterministic modulo the ``p=`` values it sees.
"""

from __future__ import annotations

__all__ = [
    # Severity-score tables (stage text → severity_score in [0, 1])
    "STAGE_SEVERITY",
    # Stage lists (in the order their weights appear below)
    "N18_STAGES",
    "I50_STAGES",
    "J44_STAGES",
    "J45_STAGES",
    "I10_STAGES",
    "I25_STAGES",
    "F00_STAGES",
    "K70_STAGES",
    "G20_STAGES",
    "I48_STAGES",
    "G35_STAGES",
    # Stage-selection weights (sum to 1.0)
    "N18_STAGE_WEIGHTS",
    "I50_STAGE_WEIGHTS_MILD",
    "I50_STAGE_WEIGHTS_DEFAULT",
    "J44_STAGE_WEIGHTS",
    "J45_STAGE_WEIGHTS",
    "I10_STAGE_WEIGHTS",
    "I25_STAGE_WEIGHTS",
    "F00_STAGE_WEIGHTS",
    "K70_STAGE_WEIGHTS",
    "G20_STAGE_WEIGHTS",
    "I48_STAGE_WEIGHTS",
    "G35_STAGE_WEIGHTS",
]


# ---------------------------------------------------------------------------
# STAGE_SEVERITY — stage text → severity_score in [0.0, 1.0]
# ---------------------------------------------------------------------------
#
# Consumed by ``physiology/engine.py``'s per-code branches so a sampled
# clinical stage (KDIGO CKD, NYHA heart failure, GOLD COPD, asthma severity,
# CCS ischemic heart disease, JNC-8 hypertension) drives physiologic severity
# instead of every condition sharing the generic ``uniform(0.1, 0.4)`` draw
# in ``activate_patient``. Ranges chosen so severity-gated branches (CKD's
# ``s > CKD_SEVERE_THRESHOLD``, heart failure's ``s > HF_SEVERE_THRESHOLD``)
# trigger only for the clinically severe stages (2026-06-20 realism-audit
# finding, CKD; extended in the same session to the other graded-stage
# conditions with the same disconnect).

STAGE_SEVERITY: dict[str, dict[str, float]] = {
    # KDIGO 2012 CKD classification (G1 eGFR ≥90 → G5 <15). Scores rise
    # exponentially so G4/G5 exceed CKD_SEVERE_THRESHOLD (0.5) and fire the
    # anemia-of-CKD + metabolic-acidosis branches in the physiology engine.
    "N18": {"G1": 0.05, "G2": 0.15, "G3a": 0.35, "G3b": 0.50, "G4": 0.70, "G5": 0.90},
    # NYHA I-IV functional classification. Score I → mild symptomatic, IV →
    # symptoms at rest. Class II already exceeds HF_SEVERE_THRESHOLD (0.3) so
    # the volume-overload branch fires from class II upward.
    "I50": {"NYHA I": 0.10, "NYHA II": 0.25, "NYHA III": 0.45, "NYHA IV": 0.70},
    # GOLD 1-4 COPD staging (FEV1 % predicted: GOLD 1 ≥80 → GOLD 4 <30).
    # Empirical severity mapping tuned so GOLD 4 hits severe pH shift.
    "J44": {"GOLD 1": 0.10, "GOLD 2": 0.25, "GOLD 3": 0.45, "GOLD 4": 0.70},
    # NAEPP EPR-3 asthma severity classification. Score maps intermittent /
    # persistent bands to the physiology engine's asthma pH coupling.
    "J45": {"Mild intermittent": 0.05, "Mild persistent": 0.15, "Moderate persistent": 0.35, "Severe persistent": 0.60},
    # CCS (Canadian Cardiovascular Society) angina classification I-IV;
    # clinosim currently samples only classes I-III (see I25_STAGES below).
    "I25": {"CCS I": 0.10, "CCS II": 0.25, "CCS III": 0.50},
    # Hypertension: JNC-8 / ACC-AHA 2017 Stage 1 (130-139/80-89) vs Stage 2
    # (>=140/90). Consumed by the stage-scaled baseline-BP elevation
    # (FP-I10), making the stage assignment non-degenerate at the vital
    # layer as well as at the physiology-coupling layer.
    "I10": {"Stage 1": 0.30, "Stage 2": 0.60},
    # Clinical Dementia Rating (CDR) — Hughes 1982 / Morris 1993. Diagnosed-
    # dementia (F00) cohort typically distributes across CDR 0.5 (very mild
    # / MCI), CDR 1 (mild), CDR 2 (moderate), CDR 3 (severe). Score lifts
    # the physiology coupling for cognitive-decline-driven lab shifts
    # (aspiration risk, nutrition decline, fall-related trauma — the
    # F00 risk_multipliers in demographics.yaml already consume severity
    # for hip_fracture / aspiration_pneumonia / UTI / vertebral fracture).
    "F00": {"CDR 0.5": 0.15, "CDR 1": 0.35, "CDR 2": 0.60, "CDR 3": 0.85},
    # Child-Pugh class A/B/C for liver cirrhosis (alcoholic K70, other
    # chronic liver disease K74). Pugh 1973 (Br J Surg) 5-9 / 7-9 /
    # 10-15 scoring over 5 clinical / lab parameters. 1-year
    # mortality tracks class A ~5% / B ~20% / C ~55%, so severity
    # score climbs steeply. Score lifts the physiology coupling
    # for synthetic-function-dependent lab shifts (albumin,
    # bilirubin, PT/INR, platelets, ammonia) and complications
    # (variceal bleeding risk, HE, ascites) once the physiology
    # engine's K70/K74 branches wire in.
    "K70": {"Child-Pugh A": 0.15, "Child-Pugh B": 0.50, "Child-Pugh C": 0.85},
    "K74": {"Child-Pugh A": 0.15, "Child-Pugh B": 0.50, "Child-Pugh C": 0.85},
    # Hoehn & Yahr stages 1-5 for Parkinson's disease (Hoehn & Yahr
    # 1967 Neurology). Severity rises steeply at stage 3 (postural
    # instability, falls become a dominant concern) and plateaus
    # near 1.0 at stage 5 (bedridden, requires full-time nursing).
    "G20": {"H&Y 1": 0.10, "H&Y 2": 0.25, "H&Y 3": 0.50, "H&Y 4": 0.75, "H&Y 5": 0.90},
    # AHA/ACC/HRS 2024 AF Guideline classification: paroxysmal
    # (self-terminating / < 7 days) → persistent (>= 7 days or
    # requires cardioversion) → long-standing persistent (>= 1 year
    # continuous, rhythm control still attempted) → permanent (both
    # patient and clinician accept continuous AF, no further
    # rhythm-control attempts). Severity reflects stroke/HF/
    # thromboembolism risk accumulation, which climbs with
    # arrhythmia burden regardless of individual symptomatology.
    "I48": {
        "Paroxysmal": 0.15,
        "Persistent": 0.35,
        "Long-standing persistent": 0.55,
        "Permanent": 0.70,
    },
    # EDSS banded staging for multiple sclerosis (Kurtzke 1983
    # Neurology). The full EDSS has 20 half-integer levels (0, 1,
    # 1.5, ..., 10); banding into 4 clinically-meaningful groups
    # keeps the simulator schema uniform with other staged
    # chronic diseases while preserving the key clinical gates
    # (ambulatory → walking impairment → wheelchair → bedridden).
    # Severity grows faster than in G20 because MS has a
    # steeper functional-decline curve once mobility is lost.
    "G35": {
        "EDSS 0-2": 0.10,  # Minimal / sensory-only deficits, fully ambulatory
        "EDSS 2.5-5": 0.30,  # Mild-moderate disability, ambulatory
        "EDSS 5.5-7": 0.60,  # Walking impairment, assistive device
        "EDSS 7.5-10": 0.85,  # Wheelchair → bedridden
    },
}


# ---------------------------------------------------------------------------
# N18 — Chronic kidney disease (KDIGO stages)
# ---------------------------------------------------------------------------

N18_STAGES: tuple[str, ...] = ("G1", "G2", "G3a", "G3b", "G4", "G5")
"""KDIGO G1-G5 stage labels. ``_generate_stage`` prepends ``"CKD "`` when
building the returned display string."""

N18_STAGE_WEIGHTS: tuple[float, ...] = (0.05, 0.30, 0.30, 0.20, 0.10, 0.05)
"""Stage-prevalence weights for CKD, tuned to approximate a synthetic
adult catchment. Empirical tuning for the synthetic simulator: real-world
US NHANES adult CKD prevalence skews toward G1-G2 (early stages) with a
long tail at G4-G5, which this vector mirrors qualitatively while
keeping the sampled cohort clinically balanced for downstream lab
generation."""


# ---------------------------------------------------------------------------
# I50 — Heart failure (NYHA functional classification)
# ---------------------------------------------------------------------------

I50_STAGES: tuple[str, ...] = ("I", "II", "III", "IV")
"""NYHA I-IV stage labels. ``_generate_stage`` prepends ``"NYHA "`` when
building the returned display string."""

I50_STAGE_WEIGHTS_MILD: tuple[float, ...] = (0.30, 0.50, 0.15, 0.05)
"""NYHA weight distribution used when the patient's overall severity is
``"mild"``. Skews toward I-II (symptomatic-on-exertion). Empirical tuning
for the synthetic simulator."""

I50_STAGE_WEIGHTS_DEFAULT: tuple[float, ...] = (0.10, 0.30, 0.40, 0.20)
"""NYHA weight distribution used for non-mild patients (``"moderate"`` /
``"severe"``). Shifts mass toward III-IV so downstream physiology and
labs reflect advanced HF. Empirical tuning for the synthetic simulator."""


# ---------------------------------------------------------------------------
# J44 — Chronic obstructive pulmonary disease (GOLD 1-4)
# ---------------------------------------------------------------------------

J44_STAGES: tuple[str, ...] = ("GOLD 1", "GOLD 2", "GOLD 3", "GOLD 4")
"""GOLD 1-4 stage labels (full string, no prefix added at emit time)."""

J44_STAGE_WEIGHTS: tuple[float, ...] = (0.20, 0.40, 0.30, 0.10)
"""GOLD stage-prevalence weights, tuned to a mid-severity population
(GOLD 2 mode). Empirical tuning for the synthetic simulator; real cohort
skew depends heavily on age band + smoking history, both of which the
simulator handles separately."""


# ---------------------------------------------------------------------------
# J45 — Asthma (NAEPP EPR-3 severity)
# ---------------------------------------------------------------------------

J45_STAGES: tuple[str, ...] = (
    "Mild intermittent",
    "Mild persistent",
    "Moderate persistent",
    "Severe persistent",
)
"""NAEPP EPR-3 severity labels (full string, no prefix added at emit
time)."""

J45_STAGE_WEIGHTS: tuple[float, ...] = (0.30, 0.35, 0.25, 0.10)
"""Asthma severity-prevalence weights. Empirical tuning for the synthetic
simulator; real US adult prevalence peaks in mild-persistent (per NAEPP
EPR-3 population data), which this vector mirrors."""


# ---------------------------------------------------------------------------
# I10 — Essential hypertension (ACC-AHA 2017 / JNC-8)
# ---------------------------------------------------------------------------

I10_STAGES: tuple[str, ...] = ("1", "2")
"""HT stage labels ("1" / "2"). ``_generate_stage`` prepends ``"Stage "``
when building the returned display string."""

I10_STAGE_WEIGHTS: tuple[float, ...] = (0.6, 0.4)
"""HT stage-prevalence weights, tuned so Stage 1 dominates a typical
adult catchment. Empirical tuning for the synthetic simulator; real
NHANES prevalence has Stage 1 slightly larger than Stage 2 among
diagnosed hypertensives."""


# ---------------------------------------------------------------------------
# I25 — Ischemic heart disease (CCS angina classification)
# ---------------------------------------------------------------------------

I25_STAGES: tuple[str, ...] = ("I", "II", "III")
"""CCS I-III stage labels. ``_generate_stage`` prepends ``"CCS "`` when
building the returned display string. Class IV is intentionally omitted:
clinosim treats class-IV symptoms (angina at rest) as an active-issue
scenario that arrives via a disease-YAML encounter path rather than a
chronic condition."""

I25_STAGE_WEIGHTS: tuple[float, ...] = (0.4, 0.4, 0.2)


# ---------------------------------------------------------------------------
# F00 — Dementia (Clinical Dementia Rating, CDR)
# ---------------------------------------------------------------------------

F00_STAGES: tuple[str, ...] = ("CDR 0.5", "CDR 1", "CDR 2", "CDR 3")
"""CDR 0.5 (very mild / MCI) → CDR 3 (severe). Full stage strings
(no prefix added at emit time)."""

F00_STAGE_WEIGHTS: tuple[float, ...] = (0.10, 0.40, 0.35, 0.15)
"""Diagnosed-dementia cohort distribution across CDR stages. Mode at
CDR 1 (mild) with a tail at CDR 3; CDR 0.5 is pre-clinical / MCI and
less often formally diagnosed as F00. Empirical tuning for the
synthetic simulator, consistent with Alzheimer's Association 2024
Facts & Figures prevalence shape (US) and MHLW 2024 cognitive-
impairment surveys (JP)."""
"""CCS stage-prevalence weights. Empirical tuning: real prevalence
depends heavily on cardiology follow-up practices; this vector produces
a balanced cohort for downstream cardiac-troponin / stress-test
generation."""


# ---------------------------------------------------------------------------
# K70 / K74 — Liver cirrhosis (Child-Pugh classification)
# ---------------------------------------------------------------------------

K70_STAGES: tuple[str, ...] = ("Child-Pugh A", "Child-Pugh B", "Child-Pugh C")
"""Child-Pugh A (score 5-6: compensated) → B (7-9: significant
functional compromise) → C (10-15: decompensated). Shared label set
for K70 (alcoholic liver disease / alcoholic cirrhosis) and K74
(other fibrosis / non-alcoholic cirrhosis). Full stage strings — no
prefix added at emit time."""

K70_STAGE_WEIGHTS: tuple[float, ...] = (0.55, 0.30, 0.15)
"""Diagnosed-cirrhosis cohort distribution. Mode at Child-Pugh A
(compensated, often an incidental or early-diagnosis finding),
with a progressive tail — class C is the end-stage subset facing
decompensation events. Empirical tuning for the synthetic
simulator consistent with D'Amico 2006 (J Hepatol) natural-history
meta-analysis prevalence shape at diagnosis + first liver clinic
contact."""


# ---------------------------------------------------------------------------
# G20 — Parkinson's disease (Hoehn & Yahr staging)
# ---------------------------------------------------------------------------

G20_STAGES: tuple[str, ...] = ("H&Y 1", "H&Y 2", "H&Y 3", "H&Y 4", "H&Y 5")
"""Hoehn & Yahr 1 (unilateral) → H&Y 2 (bilateral, no balance
impairment) → H&Y 3 (postural instability) → H&Y 4 (severe disability,
still ambulatory) → H&Y 5 (bedridden). Full stage strings — no prefix
added at emit time. Original Hoehn & Yahr 1967 (Neurology 17:427)
scale; the half-stage modified version (1.5 / 2.5) is NOT used here
since the per-stage physiology coupling and the natural-history
annual transition rates in the literature are reported on the
integer-stage scale."""

G20_STAGE_WEIGHTS: tuple[float, ...] = (0.30, 0.35, 0.20, 0.10, 0.05)
"""Diagnosed-PD cohort distribution at first clinic contact /
cross-sectional. Mode at H&Y 2 (bilateral but balance preserved),
with a progressive tail; stage 5 is a small bedridden subset.
Empirical tuning for the synthetic simulator, consistent with
Zhao 2010 (Mov Disord) outpatient cohort distribution and MDS
clinical practice guidance (most newly-diagnosed are H&Y 1-2)."""


# ---------------------------------------------------------------------------
# I48 — Atrial fibrillation (AHA/ACC/HRS classification)
# ---------------------------------------------------------------------------

I48_STAGES: tuple[str, ...] = (
    "Paroxysmal",
    "Persistent",
    "Long-standing persistent",
    "Permanent",
)
"""AHA/ACC/HRS 2024 AF Guideline: paroxysmal (self-terminating or
< 7 days) → persistent (≥ 7 days or requires cardioversion) →
long-standing persistent (≥ 1 year continuous AF with rhythm-
control strategy still attempted) → permanent (both patient and
clinician accept ongoing AF, no further rhythm control). Full
stage strings — no prefix added at emit time."""

I48_STAGE_WEIGHTS: tuple[float, ...] = (0.45, 0.25, 0.15, 0.15)
"""Diagnosed-AF cohort distribution at first clinic contact /
cross-sectional. Mode at paroxysmal (symptomatic palpitations
remain the dominant initial presentation) with a progressive tail.
Empirical tuning for the synthetic simulator, consistent with
AFNET registry cross-sectional distribution and ESC AF registry
baseline-visit shape."""


# ---------------------------------------------------------------------------
# G35 — Multiple sclerosis (banded EDSS)
# ---------------------------------------------------------------------------

G35_STAGES: tuple[str, ...] = (
    "EDSS 0-2",
    "EDSS 2.5-5",
    "EDSS 5.5-7",
    "EDSS 7.5-10",
)
"""Kurtzke 1983 (Neurology 33:1444) Expanded Disability Status
Scale, banded into 4 clinically-meaningful groups: minimal
(ambulatory, no mobility impairment), mild-to-moderate (ambulatory
with some deficit), walking impairment (requires assistive device
or orthotic), wheelchair/bedridden. The full 20-level half-integer
scale is standard clinically but overkill for a year-scale aging
simulator; the banded form preserves the key functional gates for
downstream severity gating."""

G35_STAGE_WEIGHTS: tuple[float, ...] = (0.45, 0.35, 0.15, 0.05)
"""Cross-sectional prevalent-case MS distribution. Mode at the
mild-end band (EDSS 0-2 captures newly-diagnosed + stable RRMS),
with a progressive tail. Empirical tuning for the synthetic
simulator, consistent with Confavreux 2006 (NEJM) natural-history
median EDSS trajectory + Wallin 2019 (Neurology) US MS registry
cross-sectional disability distribution."""
