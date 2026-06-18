"""Clinical course engine — YAML-driven archetype selection and state trajectory.

Reads course_archetypes from disease protocol YAML. Falls back to built-in
defaults if YAML doesn't define them. Supports complication evaluation.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from clinosim.types.clinical import StateChangeDirective
from clinosim.types.patient import PatientPhysiologicalProfile


# ============================================================
# Built-in fallback archetypes (used when YAML doesn't define trajectories)
# ============================================================

_FALLBACK_TRAJECTORIES: dict[str, dict[str, dict[int, float]]] = {
    "smooth_recovery": {
        "inflammation_level": {0: 0.05, 1: -0.02, 2: -0.08, 3: -0.08, 5: -0.06, 7: -0.06, 10: -0.04, 14: -0.02},
        "volume_status": {0: 0.02, 1: 0.03, 2: 0.03, 3: 0.02, 5: 0.01, 7: 0.01},
        "renal_function": {0: 0.00, 2: 0.01, 5: 0.01, 10: 0.01},
        "perfusion_status": {0: 0.00, 2: 0.01, 5: 0.00},
    },
    "dip_then_recovery": {
        "inflammation_level": {0: 0.10, 1: 0.05, 2: 0.02, 3: -0.02, 5: -0.08, 7: -0.10, 10: -0.08, 14: -0.05},
        "volume_status": {0: -0.05, 1: -0.03, 2: 0.02, 3: 0.03, 5: 0.02},
        "renal_function": {0: -0.02, 1: -0.01, 3: 0.01, 5: 0.01},
        "perfusion_status": {0: -0.03, 1: -0.02, 3: 0.01, 5: 0.01},
    },
    "plateau_then_recovery": {
        "inflammation_level": {0: 0.03, 1: 0.02, 3: 0.00, 5: 0.00, 7: -0.08, 10: -0.10, 14: -0.05},
        "volume_status": {0: 0.01, 1: 0.01, 5: 0.00, 7: 0.01},
    },
    "treatment_resistant": {
        "inflammation_level": {0: 0.08, 1: 0.05, 2: 0.05, 3: 0.02, 5: -0.02, 7: -0.05, 10: -0.10, 14: -0.08},
        "volume_status": {0: -0.03, 1: -0.02, 3: 0.00, 5: 0.02},
        "renal_function": {0: -0.02, 1: -0.01, 3: 0.00, 5: 0.01},
    },
    "gradual_deterioration": {
        "inflammation_level": {0: 0.10, 1: 0.08, 2: 0.08, 3: 0.05, 5: 0.05, 7: 0.03},
        "perfusion_status": {0: -0.05, 1: -0.05, 2: -0.03, 3: -0.03, 5: -0.02},
        "renal_function": {0: -0.03, 1: -0.03, 2: -0.02, 3: -0.02, 5: -0.01},
    },
    "sudden_deterioration": {
        "inflammation_level": {0: 0.05, 1: -0.02, 2: 0.30, 3: 0.10, 5: -0.05, 7: -0.08},
        "perfusion_status": {0: 0.00, 1: 0.00, 2: -0.30, 3: -0.05, 5: 0.05},
        "renal_function": {0: 0.00, 1: 0.00, 2: -0.15, 3: -0.05, 5: 0.02},
    },
}

_FALLBACK_PROBABILITIES = {
    "smooth_recovery": 0.55, "dip_then_recovery": 0.20,
    "plateau_then_recovery": 0.10, "treatment_resistant": 0.08,
    "gradual_deterioration": 0.05, "sudden_deterioration": 0.02,
}


def select_archetype(
    severity: str,
    profile: PatientPhysiologicalProfile,
    rng: np.random.Generator,
    protocol_archetypes: dict[str, Any] | None = None,
) -> str:
    """Select a clinical course archetype.

    Args:
        protocol_archetypes: course_archetypes section from disease YAML.
            If None, uses built-in fallback probabilities.
    """
    # Get probabilities from YAML or fallback
    if protocol_archetypes:
        probs = {name: a.get("probability", 0.1) for name, a in protocol_archetypes.items()}
    else:
        probs = dict(_FALLBACK_PROBABILITIES)

    # Severity modifiers
    if severity == "severe":
        probs["gradual_deterioration"] = probs.get("gradual_deterioration", 0.05) * 2.0
        probs["sudden_deterioration"] = probs.get("sudden_deterioration", 0.02) * 2.0
        probs["smooth_recovery"] = probs.get("smooth_recovery", 0.55) * 0.6
    elif severity == "mild":
        probs["smooth_recovery"] = probs.get("smooth_recovery", 0.55) * 1.3
        probs["gradual_deterioration"] = probs.get("gradual_deterioration", 0.05) * 0.3
        probs["sudden_deterioration"] = probs.get("sudden_deterioration", 0.02) * 0.3

    # Patient profile modifiers
    if profile.immune_reactivity < 0.3:
        probs["treatment_resistant"] = probs.get("treatment_resistant", 0.08) + 0.10
        probs["smooth_recovery"] = probs.get("smooth_recovery", 0.55) - 0.10
    if profile.treatment_sensitivity > 1.2:
        probs["smooth_recovery"] = probs.get("smooth_recovery", 0.55) + 0.10
        probs["treatment_resistant"] = probs.get("treatment_resistant", 0.08) - 0.05

    # Normalize
    names = list(probs.keys())
    weights = [max(0.001, probs[n]) for n in names]
    total = sum(weights)
    weights = [w / total for w in weights]

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
    # Elderly patients progress more slowly (both recovery and deterioration)
    # Young patients recover faster
    # age 40 → speed 1.2x (faster), age 70 → 1.0x, age 85 → 0.7x, age 95 → 0.5x
    if age < 50:
        speed_factor = 1.2
    elif age < 70:
        speed_factor = 1.0
    elif age < 80:
        speed_factor = 0.85
    elif age < 90:
        speed_factor = 0.7
    else:
        speed_factor = 0.55

    # Treatment sensitivity also affects speed of recovery (but not deterioration)
    recovery_speed = speed_factor * profile.treatment_sensitivity

    # --- Timing: stretch the effective day ---
    # A faster patient at "day 5" is clinically equivalent to a slower patient at "day 7"
    effective_day = day * speed_factor

    changes: dict[str, float] = {}
    for var_name in ["inflammation_level", "volume_status", "renal_function",
                     "perfusion_status", "cardiac_function", "hepatic_function",
                     "anemia_level", "coagulation_status", "ph_status", "glucose_status"]:
        if var_name in trajectory_data:
            traj = trajectory_data[var_name]
            int_traj = {int(k): v for k, v in traj.items()}
            delta = _interpolate(int_traj, effective_day)

            # --- Amplitude modulation ---
            # Immune reactivity: high → bigger inflammation swings (both up and down)
            if var_name == "inflammation_level":
                delta *= profile.immune_reactivity / 0.5

            # Recovery deltas (positive for renal/perfusion) scale with treatment sensitivity
            if delta > 0 and var_name in ("renal_function", "perfusion_status"):
                delta *= recovery_speed

            # Deterioration deltas: elderly deteriorate faster
            if delta < 0 and var_name in ("renal_function", "perfusion_status"):
                delta *= (2.0 - speed_factor)  # age 85, speed 0.7 → deterioration ×1.3

            # --- Daily noise (biological variation) ---
            # Two components:
            # 1. Proportional noise (larger swings when changing fast)
            # 2. Random daily perturbation (e.g., activity, meals, stress)
            #    This creates non-monotonic trajectories (CRP may bump up on Day 4)
            if rng is not None:
                prop_noise = float(rng.normal(0, abs(delta) * 0.15 + 0.002))
                # Occasional larger perturbation (~10% chance of a "bump day")
                if rng.random() < 0.10:
                    bump = float(rng.normal(0, 0.008))
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
        onset_range = comp.get("onset_day_range", [0, 30])
        if not (onset_range[0] <= day <= onset_range[1]):
            continue

        # Check if this is a cascade complication (requires parent)
        parent = comp.get("parent_complication")
        if parent and parent not in active_complications:
            continue

        # Calculate probability
        if parent:
            prob = comp.get("probability_given_parent", 0.1)
        else:
            prob = comp.get("probability_per_day", 0.01)

        # Apply risk factors
        for rf in comp.get("risk_factors", []):
            condition = rf.get("condition", "")
            mult = rf.get("multiplier", 1.0)
            if _evaluate_risk_condition(condition, state, patient, day):
                prob *= mult

        if rng.random() < prob:
            active_complications.add(name)
            triggered.append(comp)

    return triggered


def _evaluate_risk_condition(condition: str, state: Any, patient: Any, day: int) -> bool:
    """Evaluate a risk factor condition string against current state/patient."""
    try:
        if condition.startswith("age_over_"):
            threshold = int(condition.split("_")[-1])
            return patient.age >= threshold if hasattr(patient, "age") else False
        if condition.startswith("severity_"):
            return False  # simplified
        if "renal_function" in condition:
            parts = condition.split("<")
            if len(parts) == 2:
                return state.renal_function < float(parts[1].strip())
        if "volume_status" in condition:
            parts = condition.split("<")
            if len(parts) == 2:
                return state.volume_status < float(parts[1].strip())
        if "perfusion_status" in condition:
            parts = condition.split("<")
            if len(parts) == 2:
                return state.perfusion_status < float(parts[1].strip())
        if "delirium_susceptibility" in condition:
            parts = condition.split(">")
            if len(parts) == 2 and hasattr(patient, "physiological_profile"):
                return patient.physiological_profile.delirium_susceptibility > float(parts[1].strip())
        if "immobility_days" in condition:
            parts = condition.split(">")
            if len(parts) == 2:
                return day > int(parts[1].strip())
    except (ValueError, AttributeError):
        pass
    return False


def _interpolate(trajectory: dict[int, float], day: int) -> float:
    """Linearly interpolate between defined day points."""
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
    "renal_function", "cardiac_function", "hepatic_function", "perfusion_status",
}
# Variables where movement toward 0 = improvement
_IMPROVEMENT_TOWARD_ZERO = {"volume_status", "ph_status", "glucose_status"}


def compute_diagnosis_effectiveness(
    working_diagnosis: str | None,
    ground_truth_disease: str,
    diagnosis_confidence: float,
    day: int,
    diagnostic_difficulty: float = 0.3,
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
        return max(0.15, 0.4 - diagnostic_difficulty * 0.2)

    wd = working_diagnosis.lower().replace(" ", "_")
    gt = ground_truth_disease.lower().replace(" ", "_")

    if wd == gt or gt in wd or wd in gt:
        # Correct diagnosis — effectiveness scales with confidence
        # Harder diseases need higher confidence for full effect
        confidence_threshold = 0.3 + diagnostic_difficulty * 0.3
        if diagnosis_confidence >= confidence_threshold:
            return min(1.0, 0.6 + diagnosis_confidence * 0.4)
        return min(1.0, 0.4 + diagnosis_confidence * 0.5)

    # Wrong diagnosis — harder diseases fare worse with wrong treatment
    return max(0.05, 0.2 - diagnostic_difficulty * 0.1)


def apply_diagnosis_modifier(
    directive: StateChangeDirective,
    effectiveness: float,
    current_volume: float = 0.0,
    current_ph: float = 0.0,
) -> StateChangeDirective:
    """Dampen recovery deltas when treatment is ineffective."""
    if effectiveness >= 0.99:
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
    var: str, delta: float, current_volume: float, current_ph: float,
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
    severity_scale = {"mild": 1.2, "moderate": 1.0, "severe": 0.6}.get(severity, 1.0)
    base = 0.01 * immune * severity_scale

    # Natural recovery diminishes over time (acute phase response fades)
    if day > 7:
        base *= 0.7
    if day > 14:
        base *= 0.5

    # Anemia recovery: bone marrow erythropoiesis (~0.02/day = ~1 g/dL Hgb/week)
    # Accelerates slightly after day 3 (reticulocyte response peaks day 3-5)
    anemia_recovery = 0.015 * severity_scale
    if day >= 3:
        anemia_recovery = 0.025 * severity_scale
    if day >= 7:
        anemia_recovery = 0.02 * severity_scale  # steady-state production

    return StateChangeDirective(
        source="natural_recovery",
        changes={
            "inflammation_level": -base,
            "volume_status": -0.005 * severity_scale,  # toward 0
            "anemia_level": -anemia_recovery,  # bone marrow erythropoiesis
        },
        reason=f"Natural recovery (immune={immune:.2f}, severity={severity})",
    )
