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
    "I69_3_STAGES",
    "F32_STAGES",
    "F41_1_STAGES",
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
    "K74_STAGES",
    "K74_STAGE_WEIGHTS",
    "G20_STAGE_WEIGHTS",
    "I48_STAGE_WEIGHTS",
    "G35_STAGE_WEIGHTS",
    "I69_3_STAGE_WEIGHTS",
    "I69_1_STAGE_WEIGHTS",
    "F32_STAGE_WEIGHTS",
    "F41_1_STAGE_WEIGHTS",
]


# Issue #2289: stage labels and initial weights come from the longitudinal
# stage YAMLs (``locale/shared/longitudinal/stage/*.yaml``,
# ``initial_distribution``), the source of truth shared with the yearly
# Markov progression; only conditions without a stage YAML keep literals.


def _stage_distribution(attribute_id: str) -> dict[str, float]:
    from clinosim.modules.longitudinal.loader import load_attribute_specs
    from clinosim.modules.longitudinal.patterns.markov import MarkovSpec

    body = load_attribute_specs()[attribute_id].body
    if not isinstance(body, MarkovSpec):
        raise TypeError(f"{attribute_id} is not a Markov stage attribute")
    return dict(body.initial_distribution)


def _stage_labels(attribute_id: str) -> tuple[str, ...]:
    return tuple(_stage_distribution(attribute_id))


def _stage_weights(attribute_id: str) -> tuple[float, ...]:
    return tuple(_stage_distribution(attribute_id).values())


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
    "N18": {"CKD G1": 0.05, "CKD G2": 0.15, "CKD G3a": 0.35, "CKD G3b": 0.50, "CKD G4": 0.70, "CKD G5": 0.90},
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
    # Modified Rankin Scale (van Swieten 1988 Stroke, mRS 0-5) for
    # post-cerebral-infarction residual deficit (I69.3). mRS 6 is
    # death and handled by community mortality (population/mortality.py), not a progression
    # stage here. Severity rises steeply at mRS 3 (walking without
    # assistance becomes limited) and plateaus near 1.0 at mRS 5
    # (bedridden, requires constant nursing).
    "I69": {
        "mRS 0": 0.05,
        "mRS 1": 0.15,
        "mRS 2": 0.30,
        "mRS 3": 0.55,
        "mRS 4": 0.75,
        "mRS 5": 0.90,
    },
    # Issue #1137 — F32 / F33 depression severity bands keyed on
    # PHQ-9 total score cut-points (Kroenke 2001 JGIM 16:606).
    # Severity rises monotonically with score; "severe" exceeds the
    # 0.5 threshold used by downstream physiology branches for
    # vulnerable-patient gating. F32 and F33 share the same band
    # labels + severity map (recurrent-depression trajectory shape
    # follows single-episode once the index episode is diagnosed).
    "F32": {
        "PHQ-9 none": 0.05,
        "PHQ-9 mild": 0.15,
        "PHQ-9 moderate": 0.35,
        "PHQ-9 moderately severe": 0.55,
        "PHQ-9 severe": 0.75,
    },
    "F33": {
        "PHQ-9 none": 0.05,
        "PHQ-9 mild": 0.15,
        "PHQ-9 moderate": 0.35,
        "PHQ-9 moderately severe": 0.55,
        "PHQ-9 severe": 0.75,
    },
    # F41.1 generalized anxiety severity bands keyed on GAD-7
    # Spitzer 2006 (Arch Intern Med 166:1092) score cut-points.
    "F41.1": {
        "GAD-7 minimal": 0.05,
        "GAD-7 mild": 0.20,
        "GAD-7 moderate": 0.45,
        "GAD-7 severe": 0.70,
    },
}


# ---------------------------------------------------------------------------
# N18 — Chronic kidney disease (KDIGO stages)
# ---------------------------------------------------------------------------

N18_STAGES: tuple[str, ...] = _stage_labels("ckd_stage_n18")
"""KDIGO stage labels as stored ("CKD G1" .. "CKD G5"), from ``ckd_n18.yaml``."""

N18_STAGE_WEIGHTS: tuple[float, ...] = _stage_weights("ckd_stage_n18")
"""Stage-prevalence weights for CKD, tuned to approximate a synthetic
adult catchment. Empirical tuning for the synthetic simulator: real-world
US NHANES adult CKD prevalence skews toward G1-G2 (early stages) with a
long tail at G4-G5, which this vector mirrors qualitatively while
keeping the sampled cohort clinically balanced for downstream lab
generation."""


# ---------------------------------------------------------------------------
# I50 — Heart failure (NYHA functional classification)
# ---------------------------------------------------------------------------

I50_STAGES: tuple[str, ...] = _stage_labels("heart_failure_stage_i50")
"""NYHA class labels as stored ("NYHA I" .. "NYHA IV"), from ``heart_failure_i50.yaml``."""

I50_STAGE_WEIGHTS_MILD: tuple[float, ...] = (0.30, 0.50, 0.15, 0.05)
"""NYHA weight distribution used when the patient's overall severity is
``"mild"``. Skews toward I-II (symptomatic-on-exertion). Empirical tuning
for the synthetic simulator."""

I50_STAGE_WEIGHTS_DEFAULT: tuple[float, ...] = _stage_weights("heart_failure_stage_i50")
"""NYHA weight distribution used for non-mild patients (``"moderate"`` /
``"severe"``). Shifts mass toward III-IV so downstream physiology and
labs reflect advanced HF. Empirical tuning for the synthetic simulator."""


# ---------------------------------------------------------------------------
# J44 — Chronic obstructive pulmonary disease (GOLD 1-4)
# ---------------------------------------------------------------------------

J44_STAGES: tuple[str, ...] = _stage_labels("copd_stage_j44")
"""GOLD 1-4 stage labels (full string, no prefix added at emit time)."""

J44_STAGE_WEIGHTS: tuple[float, ...] = _stage_weights("copd_stage_j44")
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

I25_STAGES: tuple[str, ...] = _stage_labels("ischemic_heart_stage_i25")
"""CCS class labels as stored ("CCS I" .. "CCS III"), from
``ischemic_heart_i25.yaml``. Class IV is intentionally omitted:
clinosim treats class-IV symptoms (angina at rest) as an active-issue
scenario that arrives via a disease-YAML encounter path rather than a
chronic condition."""

I25_STAGE_WEIGHTS: tuple[float, ...] = _stage_weights("ischemic_heart_stage_i25")


# ---------------------------------------------------------------------------
# F00 — Dementia (Clinical Dementia Rating, CDR)
# ---------------------------------------------------------------------------

F00_STAGES: tuple[str, ...] = _stage_labels("dementia_stage_f00")
"""CDR 0.5 (very mild / MCI) → CDR 3 (severe). Full stage strings
(no prefix added at emit time)."""

F00_STAGE_WEIGHTS: tuple[float, ...] = _stage_weights("dementia_stage_f00")
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

K70_STAGES: tuple[str, ...] = _stage_labels("alcoholic_liver_stage_k70")
"""Child-Pugh A (score 5-6: compensated) → B (7-9: significant
functional compromise) → C (10-15: decompensated). Shared label set
for K70 (alcoholic liver disease / alcoholic cirrhosis) and K74
(other fibrosis / non-alcoholic cirrhosis). Full stage strings — no
prefix added at emit time."""

K70_STAGE_WEIGHTS: tuple[float, ...] = _stage_weights("alcoholic_liver_stage_k70")
"""Diagnosed-cirrhosis cohort distribution. Mode at Child-Pugh A
(compensated, often an incidental or early-diagnosis finding),
with a progressive tail — class C is the end-stage subset facing
decompensation events. Empirical tuning for the synthetic
simulator consistent with D'Amico 2006 (J Hepatol) natural-history
meta-analysis prevalence shape at diagnosis + first liver clinic
contact."""

K74_STAGES: tuple[str, ...] = _stage_labels("fibrosis_liver_stage_k74")
K74_STAGE_WEIGHTS: tuple[float, ...] = _stage_weights("fibrosis_liver_stage_k74")
"""Child-Pugh stages for non-alcoholic cirrhosis (K74), from its own
longitudinal stage YAML."""


# ---------------------------------------------------------------------------
# G20 — Parkinson's disease (Hoehn & Yahr staging)
# ---------------------------------------------------------------------------

G20_STAGES: tuple[str, ...] = _stage_labels("parkinson_stage_g20")
"""Hoehn & Yahr 1 (unilateral) → H&Y 2 (bilateral, no balance
impairment) → H&Y 3 (postural instability) → H&Y 4 (severe disability,
still ambulatory) → H&Y 5 (bedridden). Full stage strings — no prefix
added at emit time. Original Hoehn & Yahr 1967 (Neurology 17:427)
scale; the half-stage modified version (1.5 / 2.5) is NOT used here
since the per-stage physiology coupling and the natural-history
annual transition rates in the literature are reported on the
integer-stage scale."""

G20_STAGE_WEIGHTS: tuple[float, ...] = _stage_weights("parkinson_stage_g20")
"""Diagnosed-PD cohort distribution at first clinic contact /
cross-sectional. Mode at H&Y 2 (bilateral but balance preserved),
with a progressive tail; stage 5 is a small bedridden subset.
Empirical tuning for the synthetic simulator, consistent with
Zhao 2010 (Mov Disord) outpatient cohort distribution and MDS
clinical practice guidance (most newly-diagnosed are H&Y 1-2)."""


# ---------------------------------------------------------------------------
# I48 — Atrial fibrillation (AHA/ACC/HRS classification)
# ---------------------------------------------------------------------------

I48_STAGES: tuple[str, ...] = _stage_labels("atrial_fib_stage_i48")
"""AHA/ACC/HRS 2024 AF Guideline: paroxysmal (self-terminating or
< 7 days) → persistent (≥ 7 days or requires cardioversion) →
long-standing persistent (≥ 1 year continuous AF with rhythm-
control strategy still attempted) → permanent (both patient and
clinician accept ongoing AF, no further rhythm control). Full
stage strings — no prefix added at emit time."""

I48_STAGE_WEIGHTS: tuple[float, ...] = _stage_weights("atrial_fib_stage_i48")
"""Diagnosed-AF cohort distribution at first clinic contact /
cross-sectional. Mode at paroxysmal (symptomatic palpitations
remain the dominant initial presentation) with a progressive tail.
Empirical tuning for the synthetic simulator, consistent with
AFNET registry cross-sectional distribution and ESC AF registry
baseline-visit shape."""


# ---------------------------------------------------------------------------
# G35 — Multiple sclerosis (banded EDSS)
# ---------------------------------------------------------------------------

G35_STAGES: tuple[str, ...] = _stage_labels("multiple_sclerosis_stage_g35")
"""Kurtzke 1983 (Neurology 33:1444) Expanded Disability Status
Scale, banded into 4 clinically-meaningful groups: minimal
(ambulatory, no mobility impairment), mild-to-moderate (ambulatory
with some deficit), walking impairment (requires assistive device
or orthotic), wheelchair/bedridden. The full 20-level half-integer
scale is standard clinically but overkill for a year-scale aging
simulator; the banded form preserves the key functional gates for
downstream severity gating."""

G35_STAGE_WEIGHTS: tuple[float, ...] = _stage_weights("multiple_sclerosis_stage_g35")
"""Cross-sectional prevalent-case MS distribution. Mode at the
mild-end band (EDSS 0-2 captures newly-diagnosed + stable RRMS),
with a progressive tail. Empirical tuning for the synthetic
simulator, consistent with Confavreux 2006 (NEJM) natural-history
median EDSS trajectory + Wallin 2019 (Neurology) US MS registry
cross-sectional disability distribution."""


# ---------------------------------------------------------------------------
# I69.3 — Sequelae of cerebral infarction (modified Rankin Scale 0-5)
# ---------------------------------------------------------------------------

I69_3_STAGES: tuple[str, ...] = _stage_labels("stroke_sequela_stage_i69_3")
"""modified Rankin Scale (van Swieten 1988 Stroke 19:604):
  0 — no symptoms
  1 — no significant disability
  2 — slight disability (independent in self-care)
  3 — moderate disability (requires some help, walks unaided)
  4 — moderately severe (unable to walk without assistance)
  5 — severe disability (bedridden, incontinent, constant nursing)
mRS 6 (dead) is NOT a progression stage — death is driven by the
forward community-mortality draw (population/mortality.py). Full stage strings — no prefix added at
emit time."""

I69_3_STAGE_WEIGHTS: tuple[float, ...] = _stage_weights("stroke_sequela_stage_i69_3")
"""Ischemic-stroke-at-discharge mRS distribution. Benjamin 2019
(Circulation AHA Heart Disease Statistics) + GWTG-Stroke ischemic
subgroup: ~55 % discharge at mRS 0-2 (independent), ~35 % at mRS
3-4 (dependent), ~10 % at mRS 5 (severely disabled). Mean mRS
~2.5, mode mRS 2 — matches the cohort-weighted published
distribution that includes rehab-discharge improvements."""


I69_1_STAGE_WEIGHTS: tuple[float, ...] = _stage_weights("stroke_sequela_stage_i69_1")
"""Hemorrhagic-stroke-at-discharge mRS distribution — shifted
rightward (toward higher disability) compared to I69_3_STAGE_
WEIGHTS. ICH survivors have worse discharge mRS than ischemic
survivors because mass effect, hematoma expansion, and secondary
injury (perihematomal edema, intraventricular extension)
accumulate residual deficit even in those who survive the acute
event. Mean mRS ~3.1, mode mRS 3-4. Clinical basis: Kleindorfer
2021 (Stroke 52:e364) AHA/ASA Guideline for the Management of
Patients With Spontaneous Intracerebral Hemorrhage; GWTG-Stroke
hemorrhagic subgroup discharge mRS distribution; Qureshi 2001
(NEJM 344:1450) ICH natural history."""


# ---------------------------------------------------------------------------
# F32 / F33 — Depression severity bands (PHQ-9 Kroenke cut-points)
# ---------------------------------------------------------------------------

F32_STAGES: tuple[str, ...] = (
    "PHQ-9 none",
    "PHQ-9 mild",
    "PHQ-9 moderate",
    "PHQ-9 moderately severe",
    "PHQ-9 severe",
)
"""Kroenke 2001 (JGIM 16:606) PHQ-9 severity bands:
  none (0-4) / mild (5-9) / moderate (10-14) /
  moderately severe (15-19) / severe (20-27)
Shared label set for F32 (single-episode depression) and F33
(recurrent depressive disorder) — the recurrence axis does not
change the per-episode severity banding."""

F32_STAGE_WEIGHTS: tuple[float, ...] = (0.05, 0.20, 0.40, 0.25, 0.10)
"""Diagnosed-F32 outpatient cohort distribution. Mode at moderate
(10-14) with symmetric tails toward mild + moderately severe.
Empirical tuning for the synthetic simulator, consistent with
Kroenke 2001 primary-care-cohort PHQ-9 distribution (modeled
diagnosed cases, not pre-diagnosis screening cohort). The "none"
band captures remitted / stable patients on maintenance therapy."""


# ---------------------------------------------------------------------------
# F41.1 — Generalized anxiety severity bands (GAD-7 Spitzer cut-points)
# ---------------------------------------------------------------------------

F41_1_STAGES: tuple[str, ...] = (
    "GAD-7 minimal",
    "GAD-7 mild",
    "GAD-7 moderate",
    "GAD-7 severe",
)
"""Spitzer 2006 (Arch Intern Med 166:1092) GAD-7 severity bands:
  minimal (0-4) / mild (5-9) / moderate (10-14) / severe (15-21).
No "moderately severe" tier — GAD-7 collapses 15-21 into a single
severe band (fewer total items than PHQ-9)."""

F41_1_STAGE_WEIGHTS: tuple[float, ...] = (0.05, 0.30, 0.45, 0.20)
"""Diagnosed-F41.1 outpatient cohort distribution. Mode at
moderate band with mild runner-up. Empirical tuning per Spitzer
2006 + Kroenke 2007 (Ann Intern Med 146:317) primary-care GAD
cohort data."""
