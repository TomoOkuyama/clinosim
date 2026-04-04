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
                     "anemia_level", "coagulation_status", "ph_status"]:
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
            # Noise is proportional to delta magnitude, with a very small floor.
            # This prevents noise from dominating when delta is near zero (late recovery).
            if rng is not None:
                noise_sd = abs(delta) * 0.12 + 0.001
                noise = float(rng.normal(0, noise_sd))
                delta += noise

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
