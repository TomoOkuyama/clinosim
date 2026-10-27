"""Clinical course engine — YAML-driven archetype selection and state trajectory.

Reads course_archetypes from disease protocol YAML. Falls back to built-in
defaults if YAML doesn't define them. Supports complication evaluation.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from clinosim.modules._shared import normalize_probabilities
from clinosim.modules.clinical_course._archetype_modifiers import (
    AGE_SPEED_FACTOR_BANDS,
    AGE_SPEED_FACTORS,
    AGED_DETERIORATION_AMPLIFIER_BASE,
    IMMUNE_REACTIVITY_SCALE,
    MILD_GRADUAL_DETERIORATION_MULT,
    MILD_SMOOTH_RECOVERY_MULT,
    MILD_SUDDEN_DETERIORATION_MULT,
    SEVERE_GRADUAL_DETERIORATION_MULT,
    SEVERE_SMOOTH_RECOVERY_MULT,
    SEVERE_SUDDEN_DETERIORATION_MULT,
    TRAJECTORY_NOISE_FLOOR,
    TRAJECTORY_NOISE_PROP_SCALE,
)
from clinosim.modules.clinical_course._clinical_course_thresholds import (
    ANEMIA_RECOVERY_ACCEL_MIN_DAY,
    ANEMIA_RECOVERY_ACCEL_RATE,
    ANEMIA_RECOVERY_BASE_RATE,
    ANEMIA_RECOVERY_STEADY_MIN_DAY,
    ANEMIA_RECOVERY_STEADY_RATE,
    ARCHETYPE_PROBABILITY_DEFAULT,
    ARCHETYPE_WEIGHT_FLOOR,
    BUMP_DAY_PROBABILITY,
    BUMP_DAY_STD,
    COMPLICATION_ONSET_RANGE_DEFAULT,
    COMPLICATION_PROBABILITY_GIVEN_PARENT_DEFAULT,
    COMPLICATION_PROBABILITY_PER_DAY_DEFAULT,
    COMPLICATION_RISK_MULTIPLIER_DEFAULT,
    DIAGNOSIS_CONFIDENCE_THRESHOLD_BASE,
    DIAGNOSIS_CONFIDENCE_THRESHOLD_DIFFICULTY_SCALE,
    DIAGNOSIS_CORRECT_HIGH_CONF_BASE,
    DIAGNOSIS_CORRECT_HIGH_CONF_SCALE,
    DIAGNOSIS_CORRECT_LOW_CONF_BASE,
    DIAGNOSIS_CORRECT_LOW_CONF_SCALE,
    DIAGNOSIS_DIFFICULTY_DEFAULT,
    DIAGNOSIS_EFFECTIVENESS_MAX,
    DIAGNOSIS_EMPIRIC_BASE,
    DIAGNOSIS_EMPIRIC_DIFFICULTY_SCALE,
    DIAGNOSIS_EMPIRIC_FLOOR,
    DIAGNOSIS_FULL_EFFECTIVE_THRESHOLD,
    DIAGNOSIS_WRONG_BASE,
    DIAGNOSIS_WRONG_DIFFICULTY_SCALE,
    DIAGNOSIS_WRONG_FLOOR,
    NATURAL_RECOVERY_BASE_RATE,
    NATURAL_RECOVERY_LATE_DECAY_FACTOR,
    NATURAL_RECOVERY_LATE_MIN_DAY,
    NATURAL_RECOVERY_MID_DECAY_FACTOR,
    NATURAL_RECOVERY_MID_MIN_DAY,
    NATURAL_RECOVERY_SEVERITY_MILD,
    NATURAL_RECOVERY_SEVERITY_MODERATE,
    NATURAL_RECOVERY_SEVERITY_MULT_FALLBACK,
    NATURAL_RECOVERY_SEVERITY_SEVERE,
    SYMPTOM_AXIS_DAILY_RECOVERY,
    VOLUME_RECOVERY_RATE_PER_UNIT_SEVERITY,
)
from clinosim.modules.clinical_course._complication_risk_conditions import (
    CONTEXT_CONDITIONS,
    IMMOBILITY_DEFAULT_DAYS,
    MALNUTRITION_BMI_MAX,
    PATIENT_ICD_ALIASES,
    SEVERITY_ALIASES,
    STATE_ALIASES,
)
from clinosim.modules.disease.severity import EVALUABLE_CONDITIONS as PERSON_CONDITIONS
from clinosim.modules.disease.severity import _evaluate_condition as _severity_condition
from clinosim.modules.physiology.engine import canonical_state_vars
from clinosim.types.clinical import StateChangeDirective
from clinosim.types.patient import PatientPhysiologicalProfile

# Trajectory-able state vars are the delta-driven canonical set minus
# ``respiratory_fraction``, which is a one-shot routing axis
# (metabolic/mixed/respiratory) set at disease onset — not day-evolving.
# Iteration order is LOAD-BEARING for determinism (AD-16): ``get_state_changes``
# consumes ``rng`` inside the loop, so shuffling the order shifts RNG draws.
# The tuple pins the pre-FP-DELTA-VALIDATE order; the trailing
# invariant check keeps it equal to ``canonical_state_vars() - {respiratory_fraction}``
# so a physiology-model addition surfaces here as a fail-loud drift instead of a
# silent trajectory-drop.
TRAJECTORY_STATE_VARS: tuple[str, ...] = (
    "inflammation_level",
    "volume_status",
    "renal_function",
    "perfusion_status",
    "cardiac_function",
    "hepatic_function",
    "anemia_level",
    "coagulation_status",
    "ph_status",
    "glucose_status",
    "sodium_status",
    "anion_gap_status",
    "sympathetic_activation",
    "pain_level",
    "oxygenation_impairment",
    "consciousness_impairment",
)
assert frozenset(TRAJECTORY_STATE_VARS) == canonical_state_vars() - {"respiratory_fraction"}, (
    "TRAJECTORY_STATE_VARS drifted from canonical_state_vars — extend the tuple "
    "with any new physiology axis (except respiratory_fraction) to preserve "
    "the fail-loud validator gate."
)


def _validate_course_archetypes(
    disease_id: str,
    course_archetypes: dict,
) -> None:
    """Fail-loud gate for ``course_archetypes[].trajectory[]`` state-var keys.

    Sibling of :func:`clinosim.modules.physiology.engine._validate_initial_state_impact`
    — trajectory keys not in :data:`TRAJECTORY_STATE_VARS` are silently
    ignored by :func:`get_state_changes` (see the for-loop iteration on the
    hardcoded whitelist that was previously in that function). FP-DELTA-VALIDATE
    sibling sweep, .
    """
    if not course_archetypes:
        return
    offenders: list[tuple[str, str]] = []
    for arch_name, arch in (course_archetypes or {}).items():
        if not isinstance(arch, dict):
            continue
        traj = arch.get("trajectory") or {}
        if not isinstance(traj, dict):
            continue
        for var in traj:
            if var not in TRAJECTORY_STATE_VARS:
                offenders.append((arch_name, var))
    if offenders:
        details = ", ".join(f"{a!r}: {v!r}" for a, v in offenders)
        raise ValueError(
            f"Disease {disease_id!r} course_archetypes[].trajectory declares "
            f"trajectories on non-trajectory-able state var(s) [{details}] — "
            f"these would silently no-op in get_state_changes. Trajectory-able "
            f"vars: {sorted(TRAJECTORY_STATE_VARS)}. Either fix the YAML key "
            f"(typo) or expand the physiological model."
        )


# --- archetype_modifiers condition evaluation (FP-YAML-2b) ---
ARCHETYPE_EXPRESSION_VARS: frozenset[str] = frozenset(
    {"age", "immune_reactivity", "treatment_sensitivity", "prior_dka_episodes"}
)

# Disease sub-type / scenario-specific conditions used only in archetype_modifiers,
# not derivable from patient/profile. KNOWN (validation won't raise) but skipped this
# chain (reserved for the shared scenario-flag mechanism — see TODO).
ARCHETYPE_RESERVED_CONDITIONS: frozenset[str] = frozenset(
    {
        "dysphagia_known",
        "troponin_elevated_and_rv_dysfunction",
        "tpa_received",
        "injection_drug_use",
        "antiviral_within_48h",
        "prerenal_etiology",
        "active_infection",
        "hematoma_volume_above_30mL",
        "acalculous_cholecystitis",
        "prior_vte",
        "iliofemoral_location",
        "symptom_duration_over_72h",
        "symptom_duration_over_48h",
        "prior_stroke",
        "peptic_ulcer_history",
        "anterior_wall_MI",
        "prior_abdominal_surgery",
        "hernia_incarcerated",
        "medication_noncompliance",
        "sepsis",
        "prior_icu_admission",
        "prior_icu_for_asthma",
    }
)

_EXPR_RE = re.compile(r"^\s*(\w+)\s*(<=|>=|<|>|==)\s*(-?\d+(?:\.\d+)?)\s*$")
_OPS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
}


def _eval_archetype_condition(condition: str, profile: Any, patient: Any) -> bool:
    """True iff an archetype_modifier condition is active.

    Expression form (``<var> <op> <number>``) reads age (patient) or
    immune_reactivity / treatment_sensitivity (profile); unmodeled expression vars
    (prior_dka_episodes) return False. Named form delegates to the severity
    comorbidity vocabulary; reserved-intrinsic and unknown named conditions are False.
    """
    m = _EXPR_RE.match(condition or "")
    if m:
        var, op, num = m.group(1), m.group(2), float(m.group(3))
        if var == "age":
            val = float(getattr(patient, "age", 0))
        elif var in ("immune_reactivity", "treatment_sensitivity"):
            val = float(getattr(profile, var, 0.0))
        else:
            return False
        return bool(_OPS[op](val, num))
    return _severity_condition(condition, patient)


def _apply_archetype_modifiers(
    probs: dict[str, float], modifiers: list[dict[str, Any]], profile: Any, patient: Any
) -> dict[str, float]:
    """Add each active modifier's effect deltas to the archetype probabilities.

    Effect keys are validated at load to be archetypes the disease defines, so a delta
    to a non-existent archetype (silent phantom) cannot occur; guard with ``in probs``.
    """
    for mod in modifiers or []:
        if not _eval_archetype_condition(mod.get("condition", ""), profile, patient):
            continue
        for arch, delta in (mod.get("effect") or {}).items():
            if arch in probs:
                probs[arch] = probs[arch] + float(delta)
    return probs


def _validate_archetype_modifiers(disease_id: str, modifiers: list[dict[str, Any]], archetype_names: set[str]) -> None:
    """Fail-loud validation of an archetype_modifiers block at load time.

    Catches: an effect targeting an archetype the disease doesn't define (silent
    phantom), a typo'd condition (neither a parseable expression nor a known named
    condition), and a non-numeric delta.
    """
    from clinosim.modules.disease.severity import KNOWN_MODIFIER_CONDITIONS

    known_named = ARCHETYPE_RESERVED_CONDITIONS | KNOWN_MODIFIER_CONDITIONS
    for mod in modifiers or []:
        cond = mod.get("condition", "")
        if not _EXPR_RE.match(cond) and cond not in known_named:
            raise ValueError(f"{disease_id}: unknown archetype_modifier condition {cond!r}")
        for arch, delta in (mod.get("effect") or {}).items():
            if arch not in archetype_names:
                raise ValueError(
                    f"{disease_id}: archetype_modifier effect targets {arch!r} not in "
                    f"the disease's archetypes {sorted(archetype_names)}"
                )
            if not isinstance(delta, (int, float)):
                raise ValueError(f"{disease_id}: non-numeric archetype_modifier delta for {arch!r}")


# ============================================================
# Built-in fallback archetypes (used when YAML doesn't define trajectories)
# ============================================================
# Authoritative yaml:
# `clinosim/modules/clinical_course/reference_data/fallback_archetypes.yaml`
# (hardcoded-review Phase A11). The yaml carries both the per-archetype
# day-keyed trajectory tables and the probability priors; the module-
# level aliases below preserve the Python names so every call site —
# including `clinosim/modules/disease/protocol.py` which imports
# `_FALLBACK_PROBABILITIES` from this module — stays unchanged.


@cache
def _fallback_archetypes_raw() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "reference_data" / "fallback_archetypes.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _fallback_trajectories_from_yaml() -> dict[str, dict[str, dict[int, float]]]:
    archetypes = _fallback_archetypes_raw().get("archetypes", {}) or {}
    out: dict[str, dict[str, dict[int, float]]] = {}
    for name, row in archetypes.items():
        if not isinstance(row, dict):
            continue
        trajectories = row.get("trajectory", {}) or {}
        per_var: dict[str, dict[int, float]] = {}
        for state_var, points in trajectories.items():
            if not isinstance(points, dict):
                continue
            per_var[str(state_var)] = {int(day): float(delta) for day, delta in points.items()}
        out[str(name)] = per_var
    return out


def _fallback_probabilities_from_yaml() -> dict[str, float]:
    archetypes = _fallback_archetypes_raw().get("archetypes", {}) or {}
    return {
        str(name): float(row["probability"])
        for name, row in archetypes.items()
        if isinstance(row, dict) and "probability" in row
    }


_FALLBACK_TRAJECTORIES: dict[str, dict[str, dict[int, float]]] = _fallback_trajectories_from_yaml()
_FALLBACK_PROBABILITIES: dict[str, float] = _fallback_probabilities_from_yaml()


def _apply_severity_multiplier(probs: dict[str, float], archetype: str, multiplier: float) -> None:
    """Multiply an archetype's probability by ``multiplier`` in place.

    When ``probs`` lacks ``archetype`` (the YAML-driven curator may
    supply only a subset), the baseline is sourced from
    :data:`_FALLBACK_PROBABILITIES` so the six severity branches share
    a single source of truth for the pre-multiplier baseline instead
    of re-typing 0.05 / 0.02 / 0.55 inline.
    """
    probs[archetype] = probs.get(archetype, _FALLBACK_PROBABILITIES[archetype]) * multiplier


def select_archetype(
    severity: str,
    profile: PatientPhysiologicalProfile,
    rng: np.random.Generator,
    protocol_archetypes: dict[str, Any] | None = None,
    protocol_modifiers: list[dict[str, Any]] | None = None,
    patient: Any = None,
) -> str:
    """Select a clinical course archetype.

    Args:
        protocol_archetypes: course_archetypes section from disease YAML.
            If None, uses built-in fallback probabilities.
        protocol_modifiers: archetype_modifiers section from disease YAML — per-disease
            patient-risk-factor adjustments to the archetype probabilities (FP-YAML-2b).
        patient: patient object (age + chronic_conditions) for modifier evaluation.
    """
    # Get probabilities from YAML or fallback
    if protocol_archetypes:
        probs = {name: a.get("probability", ARCHETYPE_PROBABILITY_DEFAULT) for name, a in protocol_archetypes.items()}
    else:
        probs = dict(_FALLBACK_PROBABILITIES)

    # Severity modifiers — source the per-archetype fallback baseline
    # from ``_FALLBACK_PROBABILITIES`` (single source of truth) instead
    # of re-typing 0.05 / 0.02 / 0.55 inline; the values must stay
    # equal by construction but hardcoding them a second time invited
    # silent drift if the fallback dict was ever re-tuned.
    if severity == "severe":
        _apply_severity_multiplier(probs, "gradual_deterioration", SEVERE_GRADUAL_DETERIORATION_MULT)
        _apply_severity_multiplier(probs, "sudden_deterioration", SEVERE_SUDDEN_DETERIORATION_MULT)
        _apply_severity_multiplier(probs, "smooth_recovery", SEVERE_SMOOTH_RECOVERY_MULT)
    elif severity == "mild":
        _apply_severity_multiplier(probs, "smooth_recovery", MILD_SMOOTH_RECOVERY_MULT)
        _apply_severity_multiplier(probs, "gradual_deterioration", MILD_GRADUAL_DETERIORATION_MULT)
        _apply_severity_multiplier(probs, "sudden_deterioration", MILD_SUDDEN_DETERIORATION_MULT)

    # Patient risk-factor modifiers from the disease YAML (FP-YAML-2b), replacing the
    # former hardcoded immune_reactivity / treatment_sensitivity heuristics with the
    # authored, per-disease archetype_modifiers block.
    if protocol_modifiers:
        probs = _apply_archetype_modifiers(probs, protocol_modifiers, profile, patient)

    # Normalize
    names = list(probs.keys())
    weights = normalize_probabilities([max(ARCHETYPE_WEIGHT_FLOOR, probs[n]) for n in names], fallback="raise")

    return str(rng.choice(names, p=weights))


def get_daily_directive(
    archetype_name: str,
    day: int,
    profile: PatientPhysiologicalProfile,
    protocol_archetypes: dict[str, Any] | None = None,
    age: int = 70,
    rng: Any | None = None,
) -> StateChangeDirective:
    """Get the StateChangeDirective for a given day and archetype.

    Individual variation is applied through:
    1. Amplitude: immune_reactivity modulates inflammation swings
    2. Speed: age and treatment_sensitivity affect recovery/deterioration speed
    3. Timing: effective_day is shifted by age-based time stretch
    4. Noise: small random daily fluctuation (biological variation)
    """
    # Get trajectory from YAML or fallback
    if protocol_archetypes and archetype_name in protocol_archetypes:
        yaml_arch = protocol_archetypes[archetype_name]
        trajectory_data = yaml_arch.get("trajectory", {})
    else:
        trajectory_data = _FALLBACK_TRAJECTORIES.get(archetype_name, {})

    # --- Speed modulation: age-based time stretch ---
    # Elderly patients progress more slowly (both recovery and deterioration);
    # young patients recover faster. Ladder details + citations live in
    # ``_archetype_modifiers.AGE_SPEED_FACTOR_BANDS`` /
    # ``AGE_SPEED_FACTORS``.
    speed_factor = AGE_SPEED_FACTORS[-1]  # default = oldest-band factor
    for i, upper in enumerate(AGE_SPEED_FACTOR_BANDS):
        if age < upper:
            speed_factor = AGE_SPEED_FACTORS[i]
            break

    # Treatment sensitivity also affects speed of recovery (but not deterioration)
    recovery_speed = speed_factor * profile.treatment_sensitivity

    # --- Timing: stretch the effective day ---
    # A faster patient at "day 5" is clinically equivalent to a slower patient at "day 7"
    effective_day = day * speed_factor

    changes: dict[str, float] = {}
    # Trajectory-able state axes derived from canonical_state_vars (single
    # source of truth in physiology.engine). Author-time validator
    # _validate_course_archetypes rejects YAML trajectory keys outside this
    # set at load time so a typo can never silently drop again
    # (FP-DELTA-VALIDATE).
    for var_name in TRAJECTORY_STATE_VARS:
        if var_name in trajectory_data:
            traj = trajectory_data[var_name]
            int_traj = {int(k): v for k, v in traj.items()}
            delta = _interpolate(int_traj, effective_day)

            # --- Amplitude modulation ---
            # Immune reactivity: high → bigger inflammation swings (both up and down)
            if var_name == "inflammation_level":
                delta *= profile.immune_reactivity / IMMUNE_REACTIVITY_SCALE

            # Recovery deltas (positive for renal/perfusion) scale with treatment sensitivity
            if delta > 0 and var_name in ("renal_function", "perfusion_status"):
                delta *= recovery_speed

            # Deterioration deltas: elderly deteriorate faster
            if delta < 0 and var_name in ("renal_function", "perfusion_status"):
                delta *= AGED_DETERIORATION_AMPLIFIER_BASE - speed_factor

            # --- Daily noise (biological variation) ---
            # Two components:
            # 1. Proportional noise (larger swings when changing fast)
            # 2. Random daily perturbation (e.g., activity, meals, stress)
            #    This creates non-monotonic trajectories (CRP may bump up on Day 4)
            if rng is not None:
                prop_noise = float(rng.normal(0, abs(delta) * TRAJECTORY_NOISE_PROP_SCALE + TRAJECTORY_NOISE_FLOOR))
                # Occasional larger perturbation (~10% chance of a "bump day")
                if rng.random() < BUMP_DAY_PROBABILITY:
                    bump = float(rng.normal(0, BUMP_DAY_STD))
                    if var_name == "inflammation_level":
                        bump = abs(bump)  # inflammation bumps upward
                    prop_noise += bump
                delta += prop_noise

            changes[var_name] = delta

    return StateChangeDirective(
        source="disease_progression",
        changes=changes,
        reason=f"{archetype_name}_day{day}_age{age}",
    )


def evaluate_complications(
    day: int,
    state: Any,
    patient: Any,
    complications: list[dict[str, Any]],
    active_complications: set[str],
    rng: np.random.Generator,
    severity: str = "moderate",
) -> list[dict[str, Any]]:
    """Evaluate whether any complications trigger on this day.

    Returns list of triggered complications with their state_impact and actions.
    """
    triggered = []

    for comp in complications:
        name = comp.get("name", "")
        if name in active_complications:
            continue  # already active

        # Check onset window
        onset_range = comp.get("onset_day_range", COMPLICATION_ONSET_RANGE_DEFAULT)
        if not (onset_range[0] <= day <= onset_range[1]):
            continue

        # Check if this is a cascade complication (requires parent)
        parent = comp.get("parent_complication")
        if parent and parent not in active_complications:
            continue

        # Calculate probability
        if parent:
            prob = comp.get("probability_given_parent", COMPLICATION_PROBABILITY_GIVEN_PARENT_DEFAULT)
        else:
            prob = comp.get("probability_per_day", COMPLICATION_PROBABILITY_PER_DAY_DEFAULT)

        # Apply risk factors
        for rf in comp.get("risk_factors", []):
            condition = rf.get("condition", "")
            mult = rf.get("multiplier", COMPLICATION_RISK_MULTIPLIER_DEFAULT)
            if _evaluate_risk_condition(condition, state, patient, day, severity):
                prob *= mult

        if rng.random() < prob:
            active_complications.add(name)
            triggered.append(comp)

    return triggered


_STATE_THRESHOLD_RE = re.compile(r"^\s*([a-z_]+)\s*(<=|>=|<|>)\s*(-?\d+(?:\.\d+)?)\s*$")
_COMPARE = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}
_PROFILE_SUSCEPTIBILITIES = ("delirium_susceptibility", "dvt_susceptibility")


def _patient_codes(patient: Any) -> list[str]:
    return [str(getattr(c, "code", c) or "") for c in (getattr(patient, "chronic_conditions", None) or [])]


def _person_view(patient: Any) -> Any:
    """``severity._evaluate_condition`` expects ICD strings in ``chronic_conditions``;
    inpatient patients carry ``ChronicCondition`` objects."""
    from types import SimpleNamespace

    return SimpleNamespace(
        age=getattr(patient, "age", 0),
        sex=getattr(patient, "sex", ""),
        bmi=getattr(patient, "bmi", 0.0),
        smoking_status=getattr(patient, "smoking_status", "never"),
        chronic_conditions=_patient_codes(patient),
    )


def is_supported_risk_condition(condition: str) -> bool:
    """True iff ``_evaluate_risk_condition`` can resolve ``condition`` (Issue #2093)."""
    if condition.startswith(("age_over_", "age_under_")) or condition in ("severity_severe", "female"):
        return True
    if condition.startswith("immobility_days") or condition == "immobility":
        return True
    m = _STATE_THRESHOLD_RE.match(condition)
    if m and (m.group(1) in canonical_state_vars() or m.group(1) in _PROFILE_SUSCEPTIBILITIES):
        return True
    if condition in STATE_ALIASES or condition in PATIENT_ICD_ALIASES or condition in SEVERITY_ALIASES:
        return True
    if condition in ("malnutrition", "baseline_malnutrition"):
        return True
    return condition in PERSON_CONDITIONS


def validate_complication_risk_factors(disease_id: str, complications: list[dict[str, Any]]) -> None:
    """Fail loud on a complication risk-factor condition that is neither
    resolvable nor declared context (Issue #2093): a typo used to disable the
    factor silently."""
    for comp in complications or []:
        for rf in comp.get("risk_factors") or []:
            cond = str(rf.get("condition", ""))
            if not is_supported_risk_condition(cond) and cond not in CONTEXT_CONDITIONS:
                raise ValueError(
                    f"{disease_id}: complication {comp.get('name')!r} has unknown risk factor {cond!r} "
                    "(add it to _complication_risk_conditions.py)"
                )


def _evaluate_risk_condition(
    condition: str,
    state: Any,
    patient: Any,
    day: int,
    severity: str,
) -> bool:
    """Evaluate a complication risk-factor condition against the day's state and the patient.

    Vocabulary and resolution order: ``_complication_risk_conditions`` (Issue #2093).
    Declared context conditions and anything unsupported evaluate False.
    """
    try:
        if condition.startswith("age_over_"):
            return int(getattr(patient, "age", 0)) >= int(condition.split("_")[-1])
        if condition.startswith("age_under_"):
            return int(getattr(patient, "age", 999)) < int(condition.split("_")[-1])
        if condition == "severity_severe" or condition in SEVERITY_ALIASES:
            return severity == "severe"
        if condition == "female":
            return getattr(patient, "sex", "") == "F"
        if condition == "immobility":
            return day > IMMOBILITY_DEFAULT_DAYS
        if condition.startswith("immobility_days"):
            parts = condition.split(">")
            return len(parts) == 2 and day > int(parts[1].strip())
        m = _STATE_THRESHOLD_RE.match(condition)
        if m:
            var, op, value = m.group(1), m.group(2), float(m.group(3))
            if var in _PROFILE_SUSCEPTIBILITIES:
                profile = getattr(patient, "physiological_profile", None)
                return profile is not None and _COMPARE[op](float(getattr(profile, var)), value)
            if var in canonical_state_vars():
                return _COMPARE[op](float(getattr(state, var)), value)
            return False
        if condition in STATE_ALIASES:
            var, op, value = STATE_ALIASES[condition]
            return _COMPARE[op](float(getattr(state, var)), value)
        if condition in PATIENT_ICD_ALIASES:
            return any(code.startswith(PATIENT_ICD_ALIASES[condition]) for code in _patient_codes(patient))
        if condition in ("malnutrition", "baseline_malnutrition"):
            return 0 < float(getattr(patient, "bmi", 0.0) or 0.0) < MALNUTRITION_BMI_MAX
        if condition in PERSON_CONDITIONS:
            return _severity_condition(condition, _person_view(patient))
    except (ValueError, AttributeError):
        pass
    return False


def _interpolate(trajectory: dict[int, float], day: int | float) -> float:
    """Linearly interpolate between defined day points.

    accepts ``int | float`` since ``effective_day = day *
    speed_factor`` (get_daily_directive) is real-valued when speed_factor !=
    1.0. Previously the caller cast to ``int`` which truncated e.g.
    ``day=2, speed_factor=1.25 -> effective_day 2.5 -> int 2``, silently
    shifting deterioration timing (test_clinical_course caught this).
    """
    days = sorted(trajectory.keys())
    if not days:
        return 0.0
    if day <= days[0]:
        return trajectory[days[0]]
    if day >= days[-1]:
        return trajectory[days[-1]]

    for i in range(len(days) - 1):
        if days[i] <= day <= days[i + 1]:
            d0, d1 = days[i], days[i + 1]
            v0, v1 = trajectory[d0], trajectory[d1]
            frac = (day - d0) / (d1 - d0)
            return v0 + (v1 - v0) * frac

    return trajectory[days[-1]]


# ============================================================
# Diagnosis-treatment feedback
# ============================================================

# Variables where NEGATIVE delta = improvement (recovery)
_IMPROVEMENT_IS_NEGATIVE = {"inflammation_level", "anemia_level", "coagulation_status"}
# Variables where POSITIVE delta = improvement
_IMPROVEMENT_IS_POSITIVE = {
    "renal_function",
    "cardiac_function",
    "hepatic_function",
    "perfusion_status",
}
# Variables where movement toward 0 = improvement
_IMPROVEMENT_TOWARD_ZERO = {"volume_status", "ph_status", "glucose_status"}


def compute_diagnosis_effectiveness(
    working_diagnosis: str | None,
    ground_truth_disease: str,
    diagnosis_confidence: float,
    day: int,
    diagnostic_difficulty: float = DIAGNOSIS_DIFFICULTY_DEFAULT,
) -> float:
    """Compute treatment effectiveness based on diagnosis accuracy.

    Args:
        diagnostic_difficulty: 0.0 (trivial, e.g. fracture) to 1.0 (very hard).
            Higher difficulty means empiric therapy is less effective and
            correct diagnosis matters more.

    Returns 0.0-1.0 where 1.0 = fully effective treatment.
    """
    if working_diagnosis is None:
        # Empiric therapy — less effective for harder-to-diagnose conditions
        return max(
            DIAGNOSIS_EMPIRIC_FLOOR,
            DIAGNOSIS_EMPIRIC_BASE - diagnostic_difficulty * DIAGNOSIS_EMPIRIC_DIFFICULTY_SCALE,
        )

    wd = working_diagnosis.lower().replace(" ", "_")
    gt = ground_truth_disease.lower().replace(" ", "_")

    if wd == gt or gt in wd or wd in gt:
        # Correct diagnosis — effectiveness scales with confidence
        # Harder diseases need higher confidence for full effect
        confidence_threshold = (
            DIAGNOSIS_CONFIDENCE_THRESHOLD_BASE
            + diagnostic_difficulty * DIAGNOSIS_CONFIDENCE_THRESHOLD_DIFFICULTY_SCALE
        )
        if diagnosis_confidence >= confidence_threshold:
            return min(
                DIAGNOSIS_EFFECTIVENESS_MAX,
                DIAGNOSIS_CORRECT_HIGH_CONF_BASE + diagnosis_confidence * DIAGNOSIS_CORRECT_HIGH_CONF_SCALE,
            )
        return min(
            DIAGNOSIS_EFFECTIVENESS_MAX,
            DIAGNOSIS_CORRECT_LOW_CONF_BASE + diagnosis_confidence * DIAGNOSIS_CORRECT_LOW_CONF_SCALE,
        )

    # Wrong diagnosis — harder diseases fare worse with wrong treatment
    return max(
        DIAGNOSIS_WRONG_FLOOR,
        DIAGNOSIS_WRONG_BASE - diagnostic_difficulty * DIAGNOSIS_WRONG_DIFFICULTY_SCALE,
    )


def apply_diagnosis_modifier(
    directive: StateChangeDirective,
    effectiveness: float,
    current_volume: float = 0.0,
    current_ph: float = 0.0,
) -> StateChangeDirective:
    """Dampen recovery deltas when treatment is ineffective."""
    if effectiveness >= DIAGNOSIS_FULL_EFFECTIVE_THRESHOLD:
        return directive

    modified_changes: dict[str, float] = {}
    for var, delta in directive.changes.items():
        if _is_improvement(var, delta, current_volume, current_ph):
            modified_changes[var] = delta * effectiveness
        else:
            modified_changes[var] = delta

    return StateChangeDirective(
        timestamp=directive.timestamp,
        patient_id=directive.patient_id,
        source=directive.source,
        changes=modified_changes,
        reason=directive.reason,
    )


def _is_improvement(
    var: str,
    delta: float,
    current_volume: float,
    current_ph: float,
) -> bool:
    """Check if a delta represents clinical improvement."""
    if var in _IMPROVEMENT_IS_NEGATIVE:
        return delta < 0
    if var in _IMPROVEMENT_IS_POSITIVE:
        return delta > 0
    if var in _IMPROVEMENT_TOWARD_ZERO:
        current = current_volume if var == "volume_status" else current_ph
        if current > 0:
            return delta < 0
        if current < 0:
            return delta > 0
    return False


# ============================================================
# Natural recovery
# ============================================================


def natural_recovery_directive(
    day: int,
    disease_id: str,
    severity: str,
    profile: PatientPhysiologicalProfile,
) -> StateChangeDirective:
    """Compute small baseline recovery independent of treatment.

    Models the body's innate healing — immune response, homeostatic regulation.
    """
    immune = getattr(profile, "immune_reactivity", 0.5)
    severity_scale = {
        "mild": NATURAL_RECOVERY_SEVERITY_MILD,
        "moderate": NATURAL_RECOVERY_SEVERITY_MODERATE,
        "severe": NATURAL_RECOVERY_SEVERITY_SEVERE,
    }.get(severity, NATURAL_RECOVERY_SEVERITY_MULT_FALLBACK)
    base = NATURAL_RECOVERY_BASE_RATE * immune * severity_scale

    # Natural recovery diminishes over time (acute phase response fades)
    if day > NATURAL_RECOVERY_MID_MIN_DAY:
        base *= NATURAL_RECOVERY_MID_DECAY_FACTOR
    if day > NATURAL_RECOVERY_LATE_MIN_DAY:
        base *= NATURAL_RECOVERY_LATE_DECAY_FACTOR

    # Anemia recovery: bone marrow erythropoiesis (~0.02/day = ~1 g/dL Hgb/week)
    # Accelerates slightly after day 3 (reticulocyte response peaks day 3-5)
    anemia_recovery = ANEMIA_RECOVERY_BASE_RATE * severity_scale
    if day >= ANEMIA_RECOVERY_ACCEL_MIN_DAY:
        anemia_recovery = ANEMIA_RECOVERY_ACCEL_RATE * severity_scale
    if day >= ANEMIA_RECOVERY_STEADY_MIN_DAY:
        anemia_recovery = ANEMIA_RECOVERY_STEADY_RATE * severity_scale  # steady-state production

    return StateChangeDirective(
        source="natural_recovery",
        changes={
            "inflammation_level": -base,
            "volume_status": -VOLUME_RECOVERY_RATE_PER_UNIT_SEVERITY * severity_scale,  # toward 0
            "anemia_level": -anemia_recovery,  # bone marrow erythropoiesis
            **{axis: -rate for axis, rate in SYMPTOM_AXIS_DAILY_RECOVERY.items()},
        },
        reason=f"Natural recovery (immune={immune:.2f}, severity={severity})",
    )
