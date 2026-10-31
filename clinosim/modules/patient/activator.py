"""Patient activator — Layer 1 → Layer 2 conversion.

Converts a lightweight PersonRecord (population registry) into a full PatientProfile
with physiological parameters, baseline vitals, and detailed medical history.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from clinosim.locale.loader import load_names
from clinosim.modules._shared import is_jp, normalize_probabilities, resolve_lang
from clinosim.modules.patient._patient_activator_thresholds import (
    AGE_PENALTY_HEPATIC_RATIO,
    AGE_PENALTY_MIN_AGE,
    AGE_PENALTY_SCALE,
    BASELINE_DBP_AGE_REFERENCE,
    BASELINE_DBP_AGE_SCALE,
    BASELINE_DBP_BASE,
    BASELINE_DBP_SAMPLE_SD,
    BASELINE_HR_BASE_FEMALE,
    BASELINE_HR_BASE_MALE,
    BASELINE_HR_SAMPLE_SD,
    BASELINE_RR_MEAN,
    BASELINE_RR_SD,
    BASELINE_SBP_AGE_REFERENCE,
    BASELINE_SBP_AGE_SCALE,
    BASELINE_SBP_BASE,
    BASELINE_SBP_SAMPLE_SD,
    BASELINE_SPO2_CEILING,
    BASELINE_SPO2_MEAN,
    BASELINE_SPO2_SD,
    BASELINE_TEMPERATURE_MEAN,
    BASELINE_TEMPERATURE_SD,
    CHRONIC_CONTROLLED_PROBABILITY,
    CHRONIC_ONSET_DAY_MAX_EXCLUSIVE,
    CHRONIC_ONSET_DAY_MIN,
    CHRONIC_ONSET_MONTH_MAX_EXCLUSIVE,
    CHRONIC_ONSET_MONTH_MIN,
    CHRONIC_ONSET_YEAR_FLOOR,
    CHRONIC_ONSET_YEAR_MAX_EXCLUSIVE,
    CHRONIC_ONSET_YEAR_MIN,
    CHRONIC_ONSET_YEAR_REFERENCE,
    CHRONIC_SEVERITY_MILD_PROBABILITY,
    DELIRIUM_BETA_PARAMS,
    DELIRIUM_DEMENTIA_PREMIUM,
    DELIRIUM_ELDERLY_AGE_THRESHOLD,
    DELIRIUM_ELDERLY_PREMIUM,
    DELIRIUM_PARKINSON_PREMIUM,
    DRUG_METABOLISM_JP_PROBS,
    DRUG_METABOLISM_LABELS,
    DRUG_METABOLISM_US_PROBS,
    DVT_BETA_PARAMS,
    DVT_ELDERLY_AGE_THRESHOLD,
    DVT_ELDERLY_PREMIUM,
    E03_HR_REDUCTION_MAX_EXCLUSIVE,
    E03_HR_REDUCTION_MIN,
    EMERGENCY_CONTACT_ELDERLY_AGE_MIN,
    EMERGENCY_CONTACT_RELATIONS_ADULT,
    EMERGENCY_CONTACT_RELATIONS_ELDERLY,
    EMERGENCY_CONTACT_WEIGHTS_ADULT,
    EMERGENCY_CONTACT_WEIGHTS_ELDERLY,
    EMPLOYMENT_RETIREMENT_AGE_MIN,
    GENERIC_SEVERITY_UNIFORM_MAX,
    GENERIC_SEVERITY_UNIFORM_MIN,
    HEALTH_LITERACY_MEAN,
    HEALTH_LITERACY_ROUND_DIGITS,
    HEALTH_LITERACY_SD,
    I10_DBP_BASE_LIFT,
    I10_DBP_SEVERITY_SCALE,
    I10_DEFAULT_SEVERITY,
    I10_SBP_BASE_LIFT,
    I10_SBP_SEVERITY_SCALE,
    I48_HR_LIFT_MAX_EXCLUSIVE,
    I48_HR_LIFT_MIN,
    IMMUNE_REACTIVITY_BETA_PARAMS,
    J44_SPO2_LIMIT_MEAN,
    J44_SPO2_LIMIT_SD,
    J45_RR_LIFT_MAX_EXCLUSIVE,
    J45_RR_LIFT_MIN,
    MARITAL_STATUS_ADULT_AGE_MIN,
    MARITAL_STATUS_ELDERLY_CODES,
    MARITAL_STATUS_ELDERLY_WEIGHTS,
    MARITAL_STATUS_LATE_ADULT_AGE_MAX_EXCLUSIVE,
    MARITAL_STATUS_LATE_ADULT_CODES,
    MARITAL_STATUS_LATE_ADULT_WEIGHTS,
    MARITAL_STATUS_MID_ADULT_AGE_MAX_EXCLUSIVE,
    MARITAL_STATUS_MID_ADULT_CODES,
    MARITAL_STATUS_MID_ADULT_WEIGHTS,
    MARITAL_STATUS_MINOR_CODE,
    MARITAL_STATUS_YOUNG_ADULT_AGE_MAX_EXCLUSIVE,
    MARITAL_STATUS_YOUNG_ADULT_CODES,
    MARITAL_STATUS_YOUNG_ADULT_WEIGHTS,
    RESERVE_FLOOR,
    SYMPTOM_REPORTING_BIAS_MEAN,
    SYMPTOM_REPORTING_BIAS_SD,
    TREATMENT_SENSITIVITY_MEAN,
    TREATMENT_SENSITIVITY_SD,
)
from clinosim.modules.patient._severity_activation import (
    F00_STAGE_WEIGHTS,
    F00_STAGES,
    F32_STAGE_WEIGHTS,
    F32_STAGES,
    F41_1_STAGE_WEIGHTS,
    F41_1_STAGES,
    G20_STAGE_WEIGHTS,
    G20_STAGES,
    G35_STAGE_WEIGHTS,
    G35_STAGES,
    I10_STAGE_WEIGHTS,
    I10_STAGES,
    I25_STAGE_WEIGHTS,
    I25_STAGES,
    I48_STAGE_WEIGHTS,
    I48_STAGES,
    I50_STAGE_WEIGHTS_DEFAULT,
    I50_STAGE_WEIGHTS_MILD,
    I50_STAGES,
    I69_1_STAGE_WEIGHTS,
    I69_3_STAGE_WEIGHTS,
    I69_3_STAGES,
    J44_STAGE_WEIGHTS,
    J44_STAGES,
    J45_STAGE_WEIGHTS,
    J45_STAGES,
    K70_STAGE_WEIGHTS,
    K70_STAGES,
    K74_STAGE_WEIGHTS,
    K74_STAGES,
    N18_STAGE_WEIGHTS,
    N18_STAGES,
    STAGE_SEVERITY,
)
from clinosim.modules.population._pediatric_anthropometry import (
    pediatric_height_params as _peds_height_params,
)
from clinosim.modules.population._pediatric_anthropometry import (
    pediatric_upper_age as _peds_upper_age,
)
from clinosim.modules.population.engine import PersonRecord, _sample_given_name
from clinosim.types.patient import (
    BaselineVitals,
    ChronicCondition,
    HomeMedication,
    PatientPhysiologicalProfile,
    PatientProfile,
    PersonName,
)

# Physiological-reserve distribution shared by renal / cardiac / hepatic reserves.
# Issue #416: the legacy (8, 2) placed the healthy-cohort median at ~0.826, which
# combined with the derive_lab_values math pushed healthy young Cre / K / Alb /
# Troponin_I outside JP reference bands. (30, 2) shifts the median to ~0.92,
# lands ≥95% of healthy young inside the bands (measured in
# tests/unit/test_reserve_distribution_healthy_band.py), and is RNG-cursor-
# neutral vs (8, 2) — numpy's Cheng BB algorithm consumes the same number of
# uniforms per beta call for any (a > 1, b = 2). Kept module-level so the unit
# test can pin it and future tweaks stay in one place.
_RESERVE_BETA_PARAMS: tuple[float, float] = (30, 2)


def _generate_stage(code: str, severity: str, rng: np.random.Generator) -> str:
    """Generate clinical staging text for a chronic condition by ICD code.

    Stage lists and selection weights live in
    ``clinosim.modules.patient._severity_activation`` (per Issue #637
    PR-D); this function only owns the per-code branching + display-string
    formatting. The severity-score table ``STAGE_SEVERITY`` used
    downstream is imported and re-exported from the same module.
    """
    base = code.split(".")[0]
    if base == "N18":  # CKD (KDIGO G1-G5)
        return str(rng.choice(N18_STAGES, p=N18_STAGE_WEIGHTS))
    if base == "I50":  # Heart failure (NYHA I-IV)
        weights = I50_STAGE_WEIGHTS_MILD if severity == "mild" else I50_STAGE_WEIGHTS_DEFAULT
        return str(rng.choice(I50_STAGES, p=weights))
    if base == "J44":  # COPD (GOLD 1-4)
        return str(rng.choice(J44_STAGES, p=J44_STAGE_WEIGHTS))
    if base == "J45":  # Asthma (NAEPP EPR-3)
        return str(rng.choice(J45_STAGES, p=J45_STAGE_WEIGHTS))
    if base == "I10":  # Hypertension (ACC-AHA 2017 / JNC-8)
        return f"Stage {str(rng.choice(I10_STAGES, p=I10_STAGE_WEIGHTS))}"
    if base == "I25":  # Ischemic heart disease (CCS class)
        return str(rng.choice(I25_STAGES, p=I25_STAGE_WEIGHTS))
    if base == "F00":  # Dementia (Clinical Dementia Rating)
        return str(rng.choice(F00_STAGES, p=F00_STAGE_WEIGHTS))
    if base == "K70":  # Alcoholic liver disease (Child-Pugh A/B/C)
        return str(rng.choice(K70_STAGES, p=K70_STAGE_WEIGHTS))
    if base == "K74":  # Non-alcoholic cirrhosis (Child-Pugh A/B/C)
        return str(rng.choice(K74_STAGES, p=K74_STAGE_WEIGHTS))
    if base == "G20":  # Parkinson's disease (Hoehn & Yahr 1-5)
        return str(rng.choice(G20_STAGES, p=G20_STAGE_WEIGHTS))
    if base == "I48":  # Atrial fibrillation (AHA/ACC/HRS 2024)
        return str(rng.choice(I48_STAGES, p=I48_STAGE_WEIGHTS))
    if base == "G35":  # Multiple sclerosis (banded EDSS)
        return str(rng.choice(G35_STAGES, p=G35_STAGE_WEIGHTS))
    if base == "I69":  # Stroke sequelae (modified Rankin Scale)
        # I69.1 (ICH sequela) has a rightward-shifted discharge mRS vs
        # I69.3 (ischemic sequela) — hemorrhagic survivors retain more
        # residual deficit per Kleindorfer 2021 Stroke. Both share the
        # mRS stage label set (I69_3_STAGES).
        if code == "I69.1":
            return str(rng.choice(I69_3_STAGES, p=I69_1_STAGE_WEIGHTS))
        return str(rng.choice(I69_3_STAGES, p=I69_3_STAGE_WEIGHTS))
    if base in ("F32", "F33"):  # Depression severity (PHQ-9 Kroenke bands)
        return str(rng.choice(F32_STAGES, p=F32_STAGE_WEIGHTS))
    if code == "F41.1":  # Generalized anxiety severity (GAD-7 Spitzer bands)
        return str(rng.choice(F41_1_STAGES, p=F41_1_STAGE_WEIGHTS))
    return ""


# Short bilingual display per ICD-10 code — authoritative yaml at
# `clinosim/codes/data/icd10-condition-display.yaml` (hardcoded-review
# Phase A8). The yaml carries both `en` and `ja`; this `CONDITION_NAMES`
# alias preserves the historical EN-only shape so every existing call
# site (activator.py chronic-activation path + outpatient.py chronic
# visit-reason composition) stays unchanged.


_ICD10_CONDITION_DISPLAY_PATH = Path(__file__).resolve().parents[2] / "codes" / "data" / "icd10-condition-display.yaml"


@lru_cache(maxsize=1)
def _icd10_condition_display() -> dict[str, dict[str, str]]:
    """Load bilingual chronic/incident condition display from yaml."""
    with open(_ICD10_CONDITION_DISPLAY_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out: dict[str, dict[str, str]] = {}
    for code, row in (data.get("codes") or {}).items():
        if isinstance(row, dict):
            out[str(code)] = {str(k): str(v) for k, v in row.items()}
    return out


def _condition_display(code: str, lang: str = "en") -> str:
    """Return the short display label for ``code`` in ``lang``.

    Falls back to the English label when `lang` is missing from the
    row, then to the raw code — same contract as `code_lookup` so
    callers can swap this in without special-casing missing JA.
    """
    row = _icd10_condition_display().get(code, {})
    return row.get(lang) or row.get("en") or code


CONDITION_NAMES: dict[str, str] = {code: _condition_display(code, "en") for code in _icd10_condition_display()}


@lru_cache(maxsize=1)
def _chronic_onset_min_age_table() -> tuple[dict[str, int], int]:
    """Return (codes_dict, default_min_years) from the shared yaml (Issue #968)."""
    from clinosim.locale.loader import load_chronic_age_limits

    data = load_chronic_age_limits()
    codes = {str(k): int(v) for k, v in (data.get("codes") or {}).items()}
    default = int(data.get("default_min_years", 0))
    return codes, default


def _clamp_chronic_onset(sampled: date, dob: date | None, code: str) -> date:
    """Clamp a sampled chronic-condition onset date so it never precedes
    ``dob + min_onset_years[code]`` (Issue #968).

    - When ``dob`` is unknown, returns ``sampled`` unchanged (activator
      caller guarantees dob is populated for real patients).
    - The floor for a code without a yaml entry is ``dob + 1 day`` (so the
      condition can never share a day with birth itself).
    - Sampled dates after the floor pass through unmodified — the clamp is
      a floor, not a redistribution, to preserve the RNG cascade (adult
      distributions are unchanged; only pediatric edge cases move).
    """
    if dob is None:
        return sampled
    codes, default_years = _chronic_onset_min_age_table()
    min_years = codes.get(code.split(".")[0], default_years)
    # Approximate min_years by 365 * min_years days plus a 1-day floor for
    # the default=0 case so no Condition shares its subject's birth date.
    floor_days = max(1, int(min_years) * 365)
    floor = date.fromordinal(dob.toordinal() + floor_days)
    return floor if sampled < floor else sampled


def derive_implied_chronic_onset(
    patient_id: str,
    code: str,
    reference_date: date,
    dob: date | None,
) -> date:
    """Backdate an implied-chronic Condition onset deterministically from
    ``(patient_id, code)`` so it precedes the reference (acute-admission) date
    by a plausible 1-14 years — mirroring the activator's population-time
    sampling window — without consuming the master RNG (Issue #1339).

    Callers (currently ``simulator/inpatient.py``'s ``_IMPLIED_CHRONIC_BY_DISEASE``
    branch) previously stamped ``onset_date = admission_date``, which produced
    same-day "chronic condition first appearing at the acute event" records.
    That is clinically wrong: an implied chronic co-morbidity discovered on
    workup was pre-existing for years — the admission is the *documentation*
    event, not the onset.

    The offset is derived from ``SHA256(patient_id|base_code|implied_onset)``
    so patients keep the same onset across re-runs and the master-RNG cascade
    is unperturbed (see ``feedback_rng_neutral_additive_field``). Applies the
    same ``dob + min_onset_age`` floor as :func:`_clamp_chronic_onset` so
    pediatric edge cases stay clinically valid.
    """
    base_code = code.split(".")[0]
    seed = int(
        hashlib.sha256(f"{patient_id}|{base_code}|implied_onset".encode()).hexdigest()[:16],
        16,
    )
    # 1-14 years back plus 0-364 additional days (matches the activator's
    # 1..14 exclusive sampling window CHRONIC_ONSET_YEAR_MIN..MAX_EXCLUSIVE).
    years_back = 1 + (seed % 14)
    extra_days = (seed >> 16) % 365
    sampled = reference_date - timedelta(days=years_back * 365 + extra_days)
    return _clamp_chronic_onset(sampled, dob, code)


def _sample_insurance(demo: dict, age: int, rng: np.random.Generator) -> str:
    """Sample insurance type from insurance_distribution age bands."""
    bands = demo.get("insurance_distribution") or []
    for band in bands:
        lo_str, hi_str = str(band.get("age_range", "0-99")).split("-")
        if int(lo_str) <= age <= int(hi_str):
            weights_dict = band.get("weights") or {}
            if weights_dict:
                keys = list(weights_dict.keys())
                probs = normalize_probabilities([weights_dict[k] for k in keys], fallback="raise")
                return str(rng.choice(keys, p=probs))
    # Fallback: no matching band
    return ""


# Phase 1 longitudinal migration (Issue #1695): _glycemic_control_at_year
# retired. HbA1c lookup is now via
# clinosim.modules.longitudinal.engine.state_at(person, when).continuous["hba1c"]
# — see the E11 / E10 branch in _build_chronic_conditions below.


def _stage_at_year(person: PersonRecord, code_base: str, as_of_year: int | None) -> str:
    """Phase 2 longitudinal (Issue #1696) — encounter-time stage lookup.

    Walks ``person.longitudinal_history`` for the stage of ``code_base``.
    The engine's Markov pattern writes a stage only on the year(s) it
    re-draws (dense for CKD / COPD / HbA1c; sparse for F00 dementia,
    I48 AFib permanent, C-chapter cancer AJCC) so a strict year-exact
    lookup produces 93-100 % empty-stage writeback for sparse codes
    (Issue #1753). Semantics:

    * ``as_of_year`` is None → return the stage from the LATEST snapshot
      whose ``chronic_stages`` contains ``code_base``, or ``""`` if no
      snapshot ever did.
    * ``as_of_year`` is provided → return the stage from the latest
      snapshot ``s`` such that ``s.year <= as_of_year`` AND
      ``code_base in s.chronic_stages``. When no snapshot ``<= as_of_year``
      carries the stage, forward-clamp to the EARLIEST snapshot that
      does (the chronic condition is already on the problem list; the
      engine's first assignment is a better proxy than ``""``, which
      renders as "stage unknown" downstream).
    * Empty history or code never staged → ``""``.
    """
    history = person.longitudinal_history or []
    if not history:
        return ""
    # Pre-scope guard: an as_of year that precedes the person's earliest
    # snapshot year (the longitudinal engine had not yet entered scope)
    # correctly returns ``""`` — the person did not yet carry the staged
    # condition at that year, regardless of what later snapshots say.
    if as_of_year is not None and as_of_year < history[0].year:
        return ""
    # Walk history for the latest snapshot <= as_of_year that CONTAINS
    # the code. Issue #1753: pre-fix picked the latest snapshot regardless
    # of whether it carried the code, so a sparse Markov writer (F00,
    # C-chapter cancer AJCC, I48 Permanent) returned ``""`` even when
    # the stage was present in an earlier snapshot within scope.
    best_prior: str = ""
    earliest_hit: str = ""
    for snap in history:
        stage = snap.chronic_stages.get(code_base)
        if not stage:
            continue
        if not earliest_hit:
            earliest_hit = stage
        if as_of_year is None or snap.year <= as_of_year:
            best_prior = stage
    if best_prior:
        return best_prior
    # No snapshot <= as_of_year carries the stage, but a LATER snapshot
    # within scope does. Forward-clamp to that earliest hit — the chronic
    # condition is already on the problem list and the engine's first
    # assignment is a better proxy than ``""`` (which renders as "stage
    # unknown" downstream).
    return earliest_hit


def _derive_chronic_conditions(
    person: PersonRecord,
    rng: np.random.Generator,
    *,
    as_of_year: int | None = None,
) -> list[ChronicCondition]:
    """Build :class:`ChronicCondition` entries for every ICD code on
    ``person.chronic_conditions``.

    Consumes a fixed per-code RNG budget (onset-date integers, severity
    coin flip, stage draws, controlled-flag + generic-severity uniforms,
    plus two vitality-adjustment reads downstream) in a deterministic
    order so byte-identity holds across refactors. The function also
    writes staged values back to ``person.disease_stages[code_base]``
    for the aging-hook disease-progression pass (Issue #1572 Phase 2.5).

    Extracted from ``activate_patient`` as part of META #1633 P6 to
    reduce the main orchestrator's size; the body is unchanged from
    the pre-refactor inline loop.
    """
    conditions: list[ChronicCondition] = []
    for code in person.chronic_conditions:
        # Random onset year (1-15 yrs ago) and random month/day
        onset_year = max(
            CHRONIC_ONSET_YEAR_FLOOR,
            CHRONIC_ONSET_YEAR_REFERENCE - int(rng.integers(CHRONIC_ONSET_YEAR_MIN, CHRONIC_ONSET_YEAR_MAX_EXCLUSIVE)),
        )
        onset_month = int(rng.integers(CHRONIC_ONSET_MONTH_MIN, CHRONIC_ONSET_MONTH_MAX_EXCLUSIVE))
        onset_day = int(rng.integers(CHRONIC_ONSET_DAY_MIN, CHRONIC_ONSET_DAY_MAX_EXCLUSIVE))
        sev = "mild" if rng.random() < CHRONIC_SEVERITY_MILD_PROBABILITY else "moderate"
        # Stage by ICD code. For diabetes (E11/E10) the stage HbA1c, the lab HbA1c, and the
        # Glucose baseline all derive from one continuous glycemic_control axis. We reuse the
        # single float draw that _generate_stage's E11 branch used to consume (now reinterpreted
        # here) so the main RNG stream is unperturbed (AD-16).
        code_base = code.split(".")[0]
        if code_base in ("E11", "E10"):
            # Phase 1 longitudinal migration (Issue #1695): HbA1c is now
            # a first-class latent on PersonRecord.longitudinal_history.
            # Reconstruct the stage string from state_at(as_of_year).
            # The retired gc_draw / _glycemic_control_at_year /
            # hba1c_from_glycemic_control chain is gone.
            from clinosim.modules.longitudinal.engine import state_at

            hba1c_val: float | None = None
            if person.longitudinal_history:
                try:
                    snap = state_at(person, as_of_year) if as_of_year is not None else person.longitudinal_history[-1]
                    hba1c_val = snap.continuous.get("hba1c")
                except IndexError:
                    hba1c_val = None
            glycemic_control = None  # retained field preserved for downstream readers
            stage = f"HbA1c {hba1c_val:.1f}%" if hba1c_val is not None else ""
        else:
            glycemic_control = None
            # Phase 2 longitudinal (Issue #1696): when the longitudinal
            # engine owns this disease's stage (markov yaml under
            # locale/shared/longitudinal/stage/), the engine is single
            # source of truth. _generate_stage's rng.choice is still
            # consumed (value discarded) so the per-patient RNG stream
            # position for every following code is preserved — same
            # technique the diabetes hba1c_val branch uses above.
            engine_owns = any(code_base in snap.chronic_stages for snap in (person.longitudinal_history or []))
            if engine_owns:
                _ = _generate_stage(code, sev, rng)
                stage = _stage_at_year(person, code_base, as_of_year)
            else:
                stage = _generate_stage(code, sev, rng)
        # Phase 2 longitudinal: no mirror-write to person.disease_stages
        # anymore — the engine is single source of truth, read via
        # state_at / _stage_at_year. The field itself is retired in
        # Phase 2 Task 11.
        # Draw both values in the exact same order/position as before this fix
        # (controlled, then the generic severity uniform), then substitute the
        # CKD-stage-derived score for N18 afterward — the uniform draw is
        # still consumed (value discarded) so the RNG stream position for
        # every other condition/patient is unperturbed (AD-16), matching the
        # diabetes gc_draw precedent above.
        controlled_flag = rng.random() < CHRONIC_CONTROLLED_PROBABILITY
        generic_severity_score = float(rng.uniform(GENERIC_SEVERITY_UNIFORM_MIN, GENERIC_SEVERITY_UNIFORM_MAX))
        # Graded-stage conditions derive severity_score from the sampled
        # stage instead of the generic uniform(0.1, 0.4) shared by other
        # chronic conditions. STAGE_SEVERITY is keyed by the stored stage
        # label ("CKD G3b"; Issue #2289).
        severity_score = generic_severity_score
        if code_base in STAGE_SEVERITY and stage in STAGE_SEVERITY[code_base]:
            severity_score = STAGE_SEVERITY[code_base][stage]
        # Issue #968: clamp the sampled onset so it never precedes the
        # patient's date_of_birth + per-disease minimum onset age. Prior
        # to this fix pediatric patients could receive chronic conditions
        # (notably J45 asthma) with onset dates years before they were
        # born because the sampler picks an adult-typical "diagnosed
        # 1-15 years ago" window with no birthDate guard.
        _sampled_onset = date(onset_year, onset_month, onset_day)
        _dob = getattr(person, "date_of_birth", None)
        _clamped = _clamp_chronic_onset(_sampled_onset, _dob, code)
        # Cap at the reference year so a very-young patient does not get
        # an onset date far in the future. If the cap would push onset
        # below dob (patient born after ref_year), keep the birthDate
        # floor instead — never regress into pre-birth territory.
        _ref_ceiling = date(CHRONIC_ONSET_YEAR_REFERENCE, 12, 31)
        if _clamped > _ref_ceiling and _dob is not None and _ref_ceiling >= _dob:
            _clamped = _ref_ceiling
        conditions.append(
            ChronicCondition(
                code=code,
                system="icd-10-cm",
                onset_date=_clamped,
                severity=sev,
                controlled=controlled_flag,
                severity_score=severity_score,
                stage=stage,
                glycemic_control=glycemic_control,
            )
        )
    return conditions


def activate_patient(
    person: PersonRecord,
    rng: np.random.Generator,
    demo: dict,
    as_of_year: int | None = None,
) -> PatientProfile:
    """Convert Layer 1 PersonRecord to Layer 2 PatientProfile.

    ``as_of_year`` (Issue #1581): when provided, encounter-time stage
    lookups honour the year-indexed ``disease_stage_history`` so an
    encounter in sim year 1 sees the year-1 stage rather than the
    end-of-sim snapshot. ``None`` preserves the pre-#1581 behaviour
    (latest-only lookup).
    """
    age = person.age
    sex = person.sex

    # Height from physiology section; BMI already set in Layer 1
    phys = demo.get("physiology") or {}
    ht_cfg = phys.get("height_cm") or {}
    sex_key = "male" if sex == "M" else "female"

    # Derive country up front so the pediatric branch below can key
    # the correct growth-chart row before the per-age sampling runs.
    country = demo.get("_country", "US") if isinstance(demo, dict) else "US"

    # Pediatric branch (age < adult_path_min_age_years): sample height
    # from the growth-chart median for this age / sex, otherwise the
    # activator inherits the adult distribution (mean ≈ 170 / 157.5 cm)
    # and a 4-year-old lands on an adult-size stored profile. One
    # rng.normal draw either way → master-stream shape preserved.
    peds_height = _peds_height_params(country, sex, age) if age < _peds_upper_age() else None
    if peds_height is not None:
        ht_mean = peds_height["mean"]
        ht_std = peds_height["std"]
        height = float(rng.normal(ht_mean, ht_std))
    else:
        ht_mean = (ht_cfg.get(sex_key) or {}).get("mean", 170.0 if sex == "M" else 157.5)
        ht_std = (ht_cfg.get(sex_key) or {}).get("std", 5.5)
        shrink = ht_cfg.get("shrinkage_per_decade_after_60", 0.5)
        height = float(rng.normal(ht_mean, ht_std))
        if age > 60:
            height -= (age - 60) / 10 * shrink
    bmi = person.bmi
    weight = bmi * (height / 100) ** 2

    # (``country`` was derived above alongside the pediatric branch —
    # also used downstream for name formatting, language, etc.
    # Issue #570 convention: default US when demo lacks _country.)

    # Physiological profile
    age_penalty = max(0, (age - AGE_PENALTY_MIN_AGE) * AGE_PENALTY_SCALE)
    profile = PatientPhysiologicalProfile(
        immune_reactivity=float(rng.beta(*IMMUNE_REACTIVITY_BETA_PARAMS)),
        drug_metabolism_rate=str(
            rng.choice(
                DRUG_METABOLISM_LABELS,
                p=DRUG_METABOLISM_JP_PROBS if is_jp(country) else DRUG_METABOLISM_US_PROBS,
            )
        ),
        renal_reserve=max(RESERVE_FLOOR, float(rng.beta(*_RESERVE_BETA_PARAMS)) - age_penalty),
        cardiac_reserve=max(RESERVE_FLOOR, float(rng.beta(*_RESERVE_BETA_PARAMS)) - age_penalty),
        hepatic_reserve=max(
            RESERVE_FLOOR, float(rng.beta(*_RESERVE_BETA_PARAMS)) - age_penalty * AGE_PENALTY_HEPATIC_RATIO
        ),
        treatment_sensitivity=float(rng.normal(TREATMENT_SENSITIVITY_MEAN, TREATMENT_SENSITIVITY_SD)),
        symptom_reporting_bias=float(rng.normal(SYMPTOM_REPORTING_BIAS_MEAN, SYMPTOM_REPORTING_BIAS_SD)),
        delirium_susceptibility=float(rng.beta(*DELIRIUM_BETA_PARAMS))
        + (DELIRIUM_ELDERLY_PREMIUM if age >= DELIRIUM_ELDERLY_AGE_THRESHOLD else 0)
        + (DELIRIUM_DEMENTIA_PREMIUM if "F00" in person.chronic_conditions else 0)
        + (DELIRIUM_PARKINSON_PREMIUM if "G20" in person.chronic_conditions else 0),
        dvt_susceptibility=float(rng.beta(*DVT_BETA_PARAMS))
        + (DVT_ELDERLY_PREMIUM if age >= DVT_ELDERLY_AGE_THRESHOLD else 0),
    )

    # Chronic conditions (expand from ICD codes)
    conditions = _derive_chronic_conditions(person, rng, as_of_year=as_of_year)

    # Allergies — allergy_enricher (POST_POPULATION, order=10) populates person.allergies
    # before activate_patient is called in production (engine.py run_stage then _activate_cached).
    # For the debug test-encounter CLI path (no enricher), default to empty list.
    person_allergies = getattr(person, "allergies", None)
    if person_allergies is not None:
        allergies = list(person_allergies)  # enricher path — use as-is (incl. empty list)
    else:
        # Enricher did not run (debug test-encounter path); no legacy sampling needed.
        allergies = []

    # Baseline vitals
    hr_base = BASELINE_HR_BASE_MALE if sex == "M" else BASELINE_HR_BASE_FEMALE
    sbp_base = BASELINE_SBP_BASE + max(0, (age - BASELINE_SBP_AGE_REFERENCE)) * BASELINE_SBP_AGE_SCALE
    dbp_base = BASELINE_DBP_BASE + max(0, (age - BASELINE_DBP_AGE_REFERENCE)) * BASELINE_DBP_AGE_SCALE
    vitals = BaselineVitals(
        temperature=round(float(rng.normal(BASELINE_TEMPERATURE_MEAN, BASELINE_TEMPERATURE_SD)), 1),
        heart_rate=int(rng.normal(hr_base, BASELINE_HR_SAMPLE_SD)),
        systolic_bp=int(rng.normal(sbp_base, BASELINE_SBP_SAMPLE_SD)),
        diastolic_bp=int(rng.normal(dbp_base, BASELINE_DBP_SAMPLE_SD)),
        respiratory_rate=int(rng.normal(BASELINE_RR_MEAN, BASELINE_RR_SD)),
        spo2=round(float(min(BASELINE_SPO2_CEILING, rng.normal(BASELINE_SPO2_MEAN, BASELINE_SPO2_SD))), 1),
    )

    # Chronic condition adjustments to baseline vitals
    # I10 (hypertension): stage-scaled elevation (FP-I10). severity_score is 0.30
    # (Stage 1) / 0.60 (Stage 2), so Stage 2 raises BP more than Stage 1 — the stage is
    # now a real physiological consumer rather than a no-op. No new rng draw.
    _severity_by_code = {c.code: c.severity_score for c in conditions}
    if "I10" in person.chronic_conditions:
        _i10_sev = _severity_by_code.get("I10", I10_DEFAULT_SEVERITY)
        vitals.systolic_bp += int(round(I10_SBP_BASE_LIFT + _i10_sev * I10_SBP_SEVERITY_SCALE))
        vitals.diastolic_bp += int(round(I10_DBP_BASE_LIFT + _i10_sev * I10_DBP_SEVERITY_SCALE))
    if "I48" in person.chronic_conditions:
        vitals.heart_rate += int(rng.integers(I48_HR_LIFT_MIN, I48_HR_LIFT_MAX_EXCLUSIVE))  # irregularly irregular
    if "J44" in person.chronic_conditions:
        vitals.spo2 = round(min(vitals.spo2, float(rng.normal(J44_SPO2_LIMIT_MEAN, J44_SPO2_LIMIT_SD))), 1)
    if "J45" in person.chronic_conditions:
        vitals.respiratory_rate += int(rng.integers(J45_RR_LIFT_MIN, J45_RR_LIFT_MAX_EXCLUSIVE))
    if "E03" in person.chronic_conditions:
        vitals.heart_rate -= int(rng.integers(E03_HR_REDUCTION_MIN, E03_HR_REDUCTION_MAX_EXCLUSIVE))

    # Build PersonName from Layer 1 data
    if is_jp(country):
        display = f"{person.family_name} {person.given_name}"
    else:
        display = f"{person.given_name} {person.family_name}"

    name = PersonName(
        family_name=person.family_name,
        given_name=person.given_name,
        display_name=display,
        name_script=resolve_lang(country),
        phonetic=person.phonetic,
    )

    # Current medications: from Layer 1 (prior visit discharge) + chronic conditions.
    # Issue #452 PR 3: `person.current_medications` is `list[HomeMedication]`; filter
    # on `.drug_name` (an empty drug_name means the entry has no clinical meaning).
    _layer1_meds = person.current_medications if hasattr(person, "current_medications") else []
    current_meds = [m for m in _layer1_meds if m and m.drug_name]
    # Issue #1581 — hoisted out of the `if not current_meds:` branch
    # so a subsequent activate_patient call (e.g. a different
    # ``as_of_year`` for the same person after the first encounter
    # has already populated ``person.current_medications`` via
    # ``_deactivate_to_layer1``) still has a defined
    # ``_home_med_skip_log`` for the PatientProfile constructor
    # below. Empty list when the person already carries meds is
    # fine — no skip events to log for a persisted set.
    _home_med_skip_log: list = []
    # Cycle 3 C3-NEW-1 (#1745): derive the chronic base regimen UNCONDITIONALLY
    # and union with any Layer-1 pre-existing meds (dedup by drug_name).
    # Previously this was gated behind `if not current_meds:` but the
    # longitudinal engine's Phase 4a / 4b.1 escalation events
    # (htn_escalate_third_agent_i10, dm_escalate_insulin_e11, lipid_escalate_*)
    # can fire via `advance_population` BEFORE the first activate_patient
    # call for a patient, pre-populating `person.current_medications` with
    # just the escalation drug (e.g. HCTZ). The gate then skipped the base
    # derivation and 48 % of multi-chronic adults ended with ≤1 med in a
    # p=2000 US seed=42 5y audit. _derive_home_medications runs on a
    # patient-id-seeded sub-RNG, so this is RNG-shape neutral w.r.t.
    # year_rng — unrelated patients stay byte-identical.
    #
    # Derive home medications from chronic conditions via chronic_medications.yaml.
    # CIF stores English drug names (AD-30). JP names resolved at FHIR output.
    #
    # META #957 Incr 1: pregnancy prenatal supplements (folic acid,
    # iron — indexed under the Z34 key in chronic_medications.yaml)
    # were previously attached because Z34 was in chronic_conditions.
    # Post-Incr-1 Z34 lives in `state_periods` instead; when the
    # person has EVER conceived in this sim (state_history non-empty)
    # we synthesize a virtual Z34 ChronicCondition for the med-
    # derivation input ONLY so the supplement regimen still emits
    # as a home medication. The problem-list Condition emit iterates
    # the real `conditions` list (without this virtual entry) so no
    # Z34 problem-list-item leaks back in.
    #
    # ARCHITECTURAL NOTE: this activator hook attaches supplements
    # to the patient's persistent current_medications, which slightly
    # over-emits (supplements persist past the pregnancy). Proper
    # per-encounter MedicationRequest emission scoped to prenatal
    # visits is Incr 1.5. Under-emit vs the pre-Incr-1 flow (which
    # attached from Day 0 to any Z34-carrying woman, regardless of
    # actual pregnancy timing) is a net data-quality gain.
    _meds_input = conditions
    _has_pregnancy_history = bool(
        [p for p in getattr(person, "state_periods", []) or [] if getattr(p, "state_type", "") == "pregnancy"]
    )
    if _has_pregnancy_history:
        _meds_input = list(conditions) + [ChronicCondition(code="Z34", system="icd-10-cm")]
    _derived_meds = _derive_home_medications(
        _meds_input,
        patient_id=person.person_id,
        # Issue #2136: the patient's country, so ``locale_exclude`` keeps
        # drugs not marketed there (e.g. fluoxetine in JP) off the list.
        country=country,
        skip_log_out=_home_med_skip_log,
        patient_age=age,
    )
    _seen = {m.drug_name for m in current_meds if m.drug_name}
    for _hm in _derived_meds:
        if _hm.drug_name and _hm.drug_name not in _seen:
            current_meds.append(_hm)
            _seen.add(_hm.drug_name)

    # Address and contact from Layer 1
    from clinosim.types.patient import Address, ContactInfo

    address = Address(
        postal_code=getattr(person, "postal_code", ""),
        state=getattr(person, "state", ""),
        city=getattr(person, "city", ""),
        line1=getattr(person, "address_line", ""),
        country=country,
    )
    phone_mobile = getattr(person, "phone_mobile", "")
    phone_home = getattr(person, "phone_home", "")

    # Emergency contact: typically spouse for married, or child/sibling for elderly
    emergency_name = ""
    emergency_phone = ""
    emergency_rel = ""
    if age >= MARITAL_STATUS_ADULT_AGE_MIN:
        # Reuse home phone as a household contact for spouse/family
        emergency_phone = phone_home or phone_mobile
        if age >= EMERGENCY_CONTACT_ELDERLY_AGE_MIN:
            emergency_rel = str(rng.choice(EMERGENCY_CONTACT_RELATIONS_ELDERLY, p=EMERGENCY_CONTACT_WEIGHTS_ELDERLY))
        else:
            emergency_rel = str(rng.choice(EMERGENCY_CONTACT_RELATIONS_ADULT, p=EMERGENCY_CONTACT_WEIGHTS_ADULT))
        # Generate a realistic person name for the emergency contact.
        # Spouse/sibling/parent/child typically shares family name (Japan);
        # opposite sex for spouse, random for others.
        try:
            name_data = load_names(country)
            if emergency_rel == "spouse":
                contact_sex = "F" if person.sex == "M" else "M"
            else:
                contact_sex = str(rng.choice(["M", "F"]))
            given = _sample_given_name(name_data, contact_sex, rng)
            # JP uses 'kanji' key, US uses 'name' key
            given_name = given.get("kanji") or given.get("name", "")
            if not given_name:
                raise ValueError("empty given name")
            if is_jp(country):
                emergency_name = f"{name.family_name} {given_name}"
            else:
                emergency_name = f"{given_name} {name.family_name}"
        except Exception:
            # Fallback if name data unavailable. Gate on is_jp (matching the main
            # path above) — a raw country == "US" would give a lowercase "us"
            # patient the Japanese "家" suffix (FP-UNIFY-4 sibling class).
            emergency_name = f"{name.family_name}家" if is_jp(country) else f"{name.family_name} family"

    contact = ContactInfo(
        phone_home=phone_home,
        phone_mobile=phone_mobile,
        phone_primary=phone_mobile if phone_mobile else phone_home,
        emergency_contact_name=emergency_name,
        emergency_contact_phone=emergency_phone,
        emergency_contact_relationship=emergency_rel,
    )

    # Marital status (HL7 v3-MaritalStatus codes)
    if age < MARITAL_STATUS_ADULT_AGE_MIN:
        marital_status = MARITAL_STATUS_MINOR_CODE  # Never married
    elif age < MARITAL_STATUS_YOUNG_ADULT_AGE_MAX_EXCLUSIVE:
        marital_status = str(rng.choice(MARITAL_STATUS_YOUNG_ADULT_CODES, p=MARITAL_STATUS_YOUNG_ADULT_WEIGHTS))
    elif age < MARITAL_STATUS_MID_ADULT_AGE_MAX_EXCLUSIVE:
        marital_status = str(rng.choice(MARITAL_STATUS_MID_ADULT_CODES, p=MARITAL_STATUS_MID_ADULT_WEIGHTS))
    elif age < MARITAL_STATUS_LATE_ADULT_AGE_MAX_EXCLUSIVE:
        marital_status = str(rng.choice(MARITAL_STATUS_LATE_ADULT_CODES, p=MARITAL_STATUS_LATE_ADULT_WEIGHTS))
    else:
        marital_status = str(rng.choice(MARITAL_STATUS_ELDERLY_CODES, p=MARITAL_STATUS_ELDERLY_WEIGHTS))

    # Preferred language (BCP-47)
    preferred_language = "ja-JP" if is_jp(country) else "en-US"

    # Insurance type from YAML age bands
    insurance_type = _sample_insurance(demo, age, rng)
    # JP (AD-54): unify the legacy insurance_type with the identity enrollment category
    # (single source of truth), so CSV/insurance_type and FHIR Coverage stay consistent.
    if person.identity is not None:
        enrollment = person.identity.current_enrollment()
        if enrollment is not None and enrollment.category:
            insurance_type = enrollment.category

    # Race and ethnicity. Issue #1581 — the initial-cohort generator
    # now stores race / ethnicity on PersonRecord so each person has a
    # stable value across activations. When ``person.race`` is non-empty
    # we honour it, burning the ``rng.choice`` draw to preserve the
    # per-activation RNG stream shape for everything downstream (same
    # pattern as the Phase 2.5 disease-stage prefer-persisted path).
    # Test fixtures and backwards-compat callers that construct a
    # PersonRecord by hand keep the pre-#1581 behaviour (person.race
    # is "" → activator samples here).
    race_dist = demo.get("race_distribution") or {}
    if race_dist:
        rk = list(race_dist.keys())
        rp = normalize_probabilities([race_dist[k] for k in rk], fallback="raise")
        if getattr(person, "race", "") and person.race in rk:
            _ = rng.choice(rk, p=rp)  # burn the draw
            race = person.race
        else:
            race = str(rng.choice(rk, p=rp))
        eth_dist = demo.get("ethnicity_distribution") or {}
        if eth_dist:
            ek = list(eth_dist.keys())
            ep = normalize_probabilities([eth_dist[k] for k in ek], fallback="raise")
            if getattr(person, "ethnicity", "") and person.ethnicity in ek:
                _ = rng.choice(ek, p=ep)  # burn the draw
                ethnicity = person.ethnicity
            else:
                ethnicity = str(rng.choice(ek, p=ep))
        else:
            ethnicity = ""
    else:
        race = ""
        ethnicity = ""

    return PatientProfile(
        patient_id=person.person_id,
        household_id=person.household_id,
        identity=getattr(person, "identity", None),
        name=name,
        age=age,
        sex=sex,
        date_of_birth=person.date_of_birth,
        blood_type=person.blood_type,
        rh_factor=person.rh_factor,
        height_cm=round(height, 1),
        weight_kg=round(weight, 1),
        bmi=round(bmi, 1),
        address=address,
        contact=contact,
        marital_status=marital_status,
        preferred_language=preferred_language,
        employment_status="retired" if age >= EMPLOYMENT_RETIREMENT_AGE_MIN else "employed",
        occupation=getattr(person, "occupation", "other"),
        insurance_type=insurance_type,
        health_literacy=round(
            float(rng.normal(HEALTH_LITERACY_MEAN, HEALTH_LITERACY_SD)), HEALTH_LITERACY_ROUND_DIGITS
        ),
        chronic_conditions=conditions,
        allergies=allergies,
        current_medications=current_meds,
        # Issue #433 C1: immutable snapshot for renal-hold restart logic.
        # Shallow copy — subsequent encounters mutate current_medications but
        # baseline preserves the activation-time chronic regimen.
        baseline_chronic_medications=list(current_meds),
        # Issue #1066: drug_safety skip log collected during home-med
        # derivation is copied into the profile so downstream narrative /
        # audit paths can surface it.
        safety_skip_log=list(_home_med_skip_log),
        smoking_status=person.smoking_status,
        alcohol_use=person.alcohol_use,
        physiological_profile=profile,
        baseline_vitals=vitals,
        race=race,
        ethnicity=ethnicity,
        # META #957 Incr 1: forward the person's temporal-state periods
        # (pregnancy for now) so the FHIR emit adapter can derive the
        # Z37 past-birth problem-list-item Condition from delivered
        # pregnancies via ``state_history("pregnancy")``. Shallow copy —
        # PatientProfile does not mutate periods.
        state_periods=list(getattr(person, "state_periods", []) or []),
        # Cycle 2 H1 (#1735): alias (not shallow-copy) so that
        # subsequent ``advance_one_year`` appends to the shared
        # ``person.longitudinal_history`` list are visible on this
        # cached ``PatientProfile`` too. Prior ``list(...)`` wrapper
        # froze the inpatient-admit snapshot, so inpatient CIFs for
        # mid-sim admits emitted a truncated history that lost every
        # post-admit year's Phase 4a/4b/4c trajectory data.
        longitudinal_history=getattr(person, "longitudinal_history", None) or [],
        # Forward the person's recorded death date (``record_death``:
        # in-hospital or community, Issues #2166 / #2167) so FHIR emit
        # (``_build_patient``) surfaces it as ``Patient.deceasedDateTime``.
        # ``vital_status.sync_profile_death_dates`` re-syncs every profile
        # at the end of the run, so profiles activated before the death
        # carry it too.
        date_of_death=getattr(person, "date_of_death", None),
    )


def _derive_home_medications(
    chronic_conditions: list,
    rng: np.random.Generator | None = None,
    country: str = "US",
    *,
    patient_id: str = "",
    skip_log_out: list | None = None,
    patient_age: int | None = None,
) -> list[HomeMedication]:
    """Derive home medications from chronic conditions via chronic_medications.yaml.

    Per-ICD block ``exclusive_classes`` (Issue #432) lists ``drug_class``
    tags whose drugs must be selected via a mutually-exclusive categorical
    draw (at most one drug from the class). Drugs without a ``drug_class``,
    or whose class is not in the exclusive list, follow the original
    independent-Bernoulli path so clinically-valid concurrent regimens
    (e.g. I50 HF triad, I25 DAPT) stay intact.

    Categorical semantics: probabilities within an exclusive class MUST
    sum to <= 1.0. Residual mass (1 - sum) becomes the "no drug from this
    class" branch. Sum > 1.0 is a YAML author error (fail-loud).

    Returns a list of `HomeMedication` (Issue #452 PR 1). Before that PR
    this returned `list[str]`, dropping `route` / `frequency` from the
    YAML at exactly this point — the root of #442 / #445 cascade.
    Structured fields flow through to Layer 2 unchanged.
    """
    from clinosim.locale.loader import load_chronic_medications

    data = load_chronic_medications()

    # Issue #439 P1: per-patient sub-RNG for chronic-medication selection so
    # YAML edits to chronic_medications.yaml do NOT shift unrelated patients'
    # cohorts. Sibling of AD-59 panel_specimen_seed / individual_lab_seed.
    # Tests may inject an explicit rng; production callers pass patient_id
    # (rng=None) and the helper derives the sub-RNG internally.
    if rng is None:
        from clinosim.seeding import chronic_medication_seed

        if not patient_id:
            raise ValueError(
                "_derive_home_medications: either `rng` or `patient_id` must "
                "be provided (patient_id required for stable sub-RNG derivation)."
            )
        rng = np.random.default_rng(chronic_medication_seed(patient_id))

    meds: list[HomeMedication] = []
    seen: set[str] = set()
    for condition in chronic_conditions:
        code = condition.code if hasattr(condition, "code") else ""
        if not code:
            continue
        # Try exact match, then base code (e.g., E11.9 → E11, N18.3 → N18)
        spec = data.get(code) or data.get(code.split(".")[0])
        if not spec:
            continue

        exclusive_classes = set(spec.get("exclusive_classes") or ())
        medications = spec.get("medications", [])
        # Issue #1314: locale-exclude filter. Drugs whose
        # ``locale_exclude`` field lists the current country (e.g.
        # Fluoxetine on JP — not PMDA-approved) are removed from the
        # sampler input before the categorical / Bernoulli split. Kept
        # at the caller side (rather than inside
        # ``select_with_exclusive_classes``) to avoid threading
        # ``country`` through every call site; a locale-exclude gate is
        # a data-availability signal, not a probability-shape choice.
        _country_upper = str(country).strip().upper()
        medications = [
            m for m in medications if _country_upper not in {str(x).upper() for x in (m.get("locale_exclude") or [])}
        ]
        _base_code = code.split(".")[0]

        # Issue #1137 — mental-health cluster axis 6: severity-gated
        # prescribing. A drug entry's ``requires_stage_in`` field
        # (optional) lists the severity bands under which the drug
        # is a candidate; a patient whose staged severity is not in
        # that list skips the drug (its probability mass is
        # redistributed to the "no drug" branch of the sampler via
        # the exclusive-class residual). Drugs WITHOUT
        # ``requires_stage_in`` are available at every severity
        # (backward-compatible — the current F32 / F33 / F41.1
        # SSRI first-line entries remain unconditional).
        #
        # Clinical mapping (STAR*D / APA / VA-DoD): SSRI monotherapy
        # at mild and moderate; augmentation (SNRI, atypical AD)
        # at moderately severe / severe; benzodiazepine at severe
        # F41.1 (short-term).
        _mh_bases = {"F32", "F33", "F41"}
        if _base_code in _mh_bases:
            # The current loop condition is the mental-health chronic
            # itself; its ``.stage`` carries the sampled PHQ-9 /
            # GAD-7 severity band (populated by activator's
            # ``_generate_stage`` per Issue #1137 cluster axis 4).
            _patient_severity = getattr(condition, "stage", "") or ""
            medications = [
                m
                for m in medications
                if not m.get("requires_stage_in") or _patient_severity in set(m.get("requires_stage_in") or ())
            ]

        # Issue #1329: active-regimen mutex. A patient sampled into an
        # active IV chemo regimen (`chemo_regimens.yaml::by_cancer`)
        # must not simultaneously receive an oral home med whose
        # ``drug_class`` overlaps the regimen's
        # ``contains_drug_classes`` (double 5-FU exposure = severe
        # mucositis / cardiotoxicity). For C-chapter cancer codes,
        # query the shared ``pick_active_chemo_regimen`` helper on a
        # per-code sub-RNG (``chemotherapy_regimen_seed``) — the same
        # seed ``_chemo_cycle_events`` consumes — and zero the
        # ``probability`` of any conflicting med in a shallow copy of
        # its spec dict. RNG-preserving: setting ``probability=0``
        # keeps ``select_with_exclusive_classes`` consuming exactly
        # the same number of draws (Bernoulli path calls
        # ``rng.random()`` regardless of the value; exclusive-class
        # path still draws ``rng.choice`` once per class, with the
        # zeroed weight collapsing into the residual mass). Only the
        # affected patient's Capecitabine emit outcome flips; RNG
        # cursor for downstream chronic-med draws stays put.
        if _base_code.startswith("C") and _base_code[1:].isdigit() and patient_id:
            from clinosim.locale.loader import load_chemo_regimens
            from clinosim.modules.population.engine import pick_active_chemo_regimen
            from clinosim.seeding import chemotherapy_regimen_seed

            _chemo_data = load_chemo_regimens()
            _chemo_regimens = _chemo_data.get("regimens") or {}
            _by_cancer = _chemo_data.get("by_cancer") or {}
            _chemo_rng = np.random.default_rng(chemotherapy_regimen_seed(patient_id, _base_code))
            _picked = pick_active_chemo_regimen(_chemo_rng, _chemo_regimens, _by_cancer, _base_code)
            if _picked is not None:
                _, _regimen = _picked
                _conflict_classes = {str(x) for x in (_regimen.get("contains_drug_classes") or [])}
                if _conflict_classes:
                    medications = [
                        (m if str(m.get("drug_class") or "") not in _conflict_classes else {**m, "probability": 0.0})
                        for m in medications
                    ]

        # Single-mechanism selection: exclusive_classes categorical + non-exclusive
        # independent Bernoulli. Shared with `_build_discharge_rx` — see
        # `select_with_exclusive_classes` in clinosim.modules._shared.
        from clinosim.modules._shared import select_with_exclusive_classes

        for picked in select_with_exclusive_classes(
            medications,
            exclusive_classes,
            rng,
            independent_mode="bernoulli",
            context=f"chronic_medications ICD {code}",
            patient_age=patient_age,
        ):
            # Issue #1804 Phase 2.a: prefer the catalog's resolve_drug when
            # the yaml entry carries drug_id; fall back to the legacy
            # drug / drug_ja fields for entries not yet migrated
            # (Rivaroxaban dose-embedded, Tegafur-Gimeracil-Oteracil combo).
            # The catalog is the display SoT once a drug_id is set;
            # legacy entries render from their inline yaml strings.
            drug_id = picked.get("drug_id") or ""
            if drug_id:
                from clinosim.codes.drugs import resolve_drug

                _rec = resolve_drug(drug_id)
                drug_en = _rec.names.get("en", "") or ""
                drug_ja = _rec.names.get("ja", "") or ""
            else:
                drug_en = picked.get("drug", "")
                drug_ja = picked.get("drug_ja", "")
            # CIF stores English drug names (AD-30). JP display picks up drug_ja
            # at output time. Selection key uses the string that reaches the
            # display side so JP and US dedup identically.
            name_for_display = drug_ja if is_jp(country) else drug_en
            if not name_for_display or name_for_display in seen:
                continue

            # Issue #1066: drug_safety CPOE-style gate for chronic co-prescriptions.
            # The activator is the point where warfarin+aspirin (both chronic)
            # pairs form — check each candidate against already-accepted home
            # meds and skip on major/contraindicated severity. Substitution
            # for chronic meds is out of scope for MVP; a skipped chronic
            # candidate is simply dropped (Warfarin already covers the AF
            # anticoagulation indication, so the Aspirin skip does not leave
            # a therapy gap).
            from clinosim.modules import drug_safety
            from clinosim.modules.drug_safety.verdict import (
                SEVERITY_RANK,
                SafetySkipEntry,
            )

            candidate_drug = drug_en if drug_en else name_for_display
            active_drug_names = [m.drug_name for m in meds if m.drug_name]
            drug_verdicts = drug_safety.check_candidate_against_active(candidate_drug, active_drug_names)
            # Issue #1392 Cluster A: also gate on drug-vs-active-disease
            # (NSAID vs HF / cirrhosis / CKD stage 4-5). The patient's
            # chronic-condition list is the full carrier set at this point
            # in activation. Codes are stored as their base form (I50, K74,
            # N18) with any stage in ``ChronicCondition.stage`` ("CKD G4");
            # stage-contingent rules match on the stage (Issue #2282).
            # Issue #1769: pass (code, stage) tuples so a stage-contingent
            # rule (Metformin + CKD G3b-G5) can distinguish the N18
            # severity bands. Bare-string code is retained for conditions
            # without a staged ``.stage`` attribute (fail-closed on
            # ``stage_in`` rules, no behavior change for others).
            active_condition_entries = [
                (cond.code, getattr(cond, "stage", "") or "")
                for cond in chronic_conditions
                if hasattr(cond, "code") and cond.code
            ]
            disease_verdicts = drug_safety.check_candidate_against_disease_state(
                candidate_drug, active_condition_entries
            )
            verdicts = list(drug_verdicts) + list(disease_verdicts)
            worst = max(
                (v for v in verdicts if not v.is_allowed),
                key=lambda v: SEVERITY_RANK[v.severity],
                default=None,
            )
            if worst is not None and worst.default_action == "skip":
                if skip_log_out is not None:
                    skip_log_out.append(
                        SafetySkipEntry(
                            encounter_id="__home_med_derivation__",
                            candidate_drug=candidate_drug,
                            candidate_drug_ja=(
                                drug_safety.japanese_display(candidate_drug) or drug_ja or candidate_drug
                            ),
                            active_conflict=worst.matched_active_drug or "",
                            active_conflict_ja=(
                                drug_safety.japanese_display(worst.matched_active_drug or "")
                                or (worst.matched_active_drug or "")
                            ),
                            verdict=worst,
                            substituted_with=None,
                            substituted_with_ja=None,
                            context_hint="home_med_derivation",
                            timestamp="",
                        )
                    )
                continue  # drop the contraindicated chronic candidate

            seen.add(name_for_display)
            meds.append(
                HomeMedication(
                    drug_name=candidate_drug,
                    drug_name_ja=drug_ja,
                    route=str(picked.get("route", "") or ""),
                    dose=str(picked.get("dose", "") or ""),
                    frequency=str(picked.get("frequency", "") or ""),
                )
            )
    return meds
