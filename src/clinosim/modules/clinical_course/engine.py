"""Clinical course engine — archetype selection and state trajectory generation.

Selects a clinical course archetype for each patient based on disease protocol
and patient profile, then generates daily StateChangeDirectives.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from clinosim.types.clinical import StateChangeDirective
from clinosim.types.patient import PatientPhysiologicalProfile


# ============================================================
# Archetype definitions (hardcoded for alpha/beta; YAML-driven later)
# ============================================================

@dataclass
class ArchetypeTrajectory:
    """Daily deltas for each state variable, keyed by day number."""
    name: str
    base_probability: float
    inflammation: dict[int, float]  # day → daily delta
    volume: dict[int, float]
    renal: dict[int, float]
    perfusion: dict[int, float]
    description: str = ""


ARCHETYPES: dict[str, ArchetypeTrajectory] = {
    "smooth_recovery": ArchetypeTrajectory(
        name="smooth_recovery",
        base_probability=0.55,
        description="Steady improvement from Day 1-2 after treatment",
        inflammation={0: 0.05, 1: -0.02, 2: -0.08, 3: -0.08, 5: -0.06, 7: -0.06, 10: -0.04, 14: -0.02},
        volume={0: 0.02, 1: 0.03, 2: 0.03, 3: 0.02, 5: 0.01, 7: 0.01, 10: 0.00, 14: 0.00},
        renal={0: 0.00, 1: 0.00, 2: 0.01, 3: 0.01, 5: 0.01, 7: 0.01, 10: 0.01, 14: 0.01},
        perfusion={0: 0.00, 1: 0.00, 2: 0.01, 3: 0.01, 5: 0.00, 7: 0.00, 10: 0.00, 14: 0.00},
    ),
    "dip_then_recovery": ArchetypeTrajectory(
        name="dip_then_recovery",
        base_probability=0.20,
        description="Worsening Day 1-3, then gradual improvement",
        inflammation={0: 0.10, 1: 0.05, 2: 0.02, 3: -0.02, 5: -0.08, 7: -0.10, 10: -0.08, 14: -0.05},
        volume={0: -0.05, 1: -0.03, 2: 0.02, 3: 0.03, 5: 0.02, 7: 0.01, 10: 0.00, 14: 0.00},
        renal={0: -0.02, 1: -0.01, 2: 0.00, 3: 0.01, 5: 0.01, 7: 0.01, 10: 0.01, 14: 0.01},
        perfusion={0: -0.03, 1: -0.02, 2: 0.00, 3: 0.01, 5: 0.01, 7: 0.00, 10: 0.00, 14: 0.00},
    ),
    "plateau_then_recovery": ArchetypeTrajectory(
        name="plateau_then_recovery",
        base_probability=0.10,
        description="No change for 3-5 days, then improvement",
        inflammation={0: 0.03, 1: 0.02, 2: 0.00, 3: 0.00, 5: 0.00, 7: -0.08, 10: -0.10, 14: -0.05},
        volume={0: 0.01, 1: 0.01, 2: 0.01, 3: 0.00, 5: 0.00, 7: 0.01, 10: 0.01, 14: 0.00},
        renal={0: 0.00, 1: 0.00, 2: 0.00, 3: 0.00, 5: 0.00, 7: 0.01, 10: 0.01, 14: 0.01},
        perfusion={0: 0.00, 1: 0.00, 2: 0.00, 3: 0.00, 5: 0.00, 7: 0.01, 10: 0.00, 14: 0.00},
    ),
    "treatment_resistant": ArchetypeTrajectory(
        name="treatment_resistant",
        base_probability=0.08,
        description="No response to first-line; requires change at Day 3-5",
        inflammation={0: 0.08, 1: 0.05, 2: 0.05, 3: 0.02, 5: -0.02, 7: -0.05, 10: -0.10, 14: -0.08},
        volume={0: -0.03, 1: -0.02, 2: -0.01, 3: 0.00, 5: 0.02, 7: 0.02, 10: 0.01, 14: 0.00},
        renal={0: -0.02, 1: -0.01, 2: -0.01, 3: 0.00, 5: 0.01, 7: 0.01, 10: 0.01, 14: 0.01},
        perfusion={0: -0.02, 1: -0.01, 2: -0.01, 3: 0.00, 5: 0.01, 7: 0.01, 10: 0.00, 14: 0.00},
    ),
    "gradual_deterioration": ArchetypeTrajectory(
        name="gradual_deterioration",
        base_probability=0.05,
        description="Slow worsening despite treatment -> ICU",
        inflammation={0: 0.10, 1: 0.08, 2: 0.08, 3: 0.05, 5: 0.05, 7: 0.03, 10: 0.02, 14: 0.00},
        volume={0: -0.05, 1: -0.03, 2: -0.02, 3: -0.02, 5: 0.05, 7: 0.08, 10: 0.05, 14: 0.02},
        renal={0: -0.03, 1: -0.03, 2: -0.02, 3: -0.02, 5: -0.01, 7: 0.00, 10: 0.01, 14: 0.01},
        perfusion={0: -0.05, 1: -0.05, 2: -0.03, 3: -0.03, 5: -0.02, 7: 0.00, 10: 0.01, 14: 0.01},
    ),
    "sudden_deterioration": ArchetypeTrajectory(
        name="sudden_deterioration",
        base_probability=0.02,
        description="Sudden critical worsening (sepsis, PE)",
        inflammation={0: 0.05, 1: -0.02, 2: 0.30, 3: 0.10, 5: -0.05, 7: -0.08, 10: -0.06, 14: -0.03},
        volume={0: 0.00, 1: 0.00, 2: -0.20, 3: 0.10, 5: 0.05, 7: 0.02, 10: 0.01, 14: 0.00},
        renal={0: 0.00, 1: 0.00, 2: -0.15, 3: -0.05, 5: 0.02, 7: 0.02, 10: 0.01, 14: 0.01},
        perfusion={0: 0.00, 1: 0.00, 2: -0.30, 3: -0.05, 5: 0.05, 7: 0.05, 10: 0.02, 14: 0.01},
    ),
}


def select_archetype(
    severity: str,
    profile: PatientPhysiologicalProfile,
    rng: np.random.Generator,
) -> str:
    """Select a clinical course archetype based on severity and patient profile."""
    probs = {name: a.base_probability for name, a in ARCHETYPES.items()}

    # Severity modifiers
    if severity == "severe":
        probs["gradual_deterioration"] *= 2.0
        probs["sudden_deterioration"] *= 2.0
        probs["smooth_recovery"] *= 0.6
    elif severity == "mild":
        probs["smooth_recovery"] *= 1.3
        probs["gradual_deterioration"] *= 0.3
        probs["sudden_deterioration"] *= 0.3

    # Patient profile modifiers
    if profile.immune_reactivity < 0.3:
        probs["treatment_resistant"] += 0.10
        probs["smooth_recovery"] -= 0.10
    if profile.treatment_sensitivity > 1.2:
        probs["smooth_recovery"] += 0.10
        probs["treatment_resistant"] -= 0.05

    # Normalize
    total = sum(probs.values())
    names = list(probs.keys())
    weights = [max(0, probs[n]) / total for n in names]

    return str(rng.choice(names, p=weights))


def get_daily_directive(
    archetype_name: str,
    day: int,
    profile: PatientPhysiologicalProfile,
) -> StateChangeDirective:
    """Get the StateChangeDirective for a given day and archetype.

    Interpolates between defined day points and modulates by patient profile.
    """
    archetype = ARCHETYPES[archetype_name]

    changes: dict[str, float] = {}
    for var_name, attr in [
        ("inflammation_level", "inflammation"),
        ("volume_status", "volume"),
        ("renal_function", "renal"),
        ("perfusion_status", "perfusion"),
    ]:
        trajectory = getattr(archetype, attr)
        delta = _interpolate(trajectory, day)

        # Patient modulation
        if var_name == "inflammation_level":
            delta *= profile.immune_reactivity / 0.5  # higher reactivity = bigger swings
        if var_name in ("renal_function", "perfusion_status") and delta > 0:
            delta *= profile.treatment_sensitivity  # higher sensitivity = faster recovery

        changes[var_name] = delta

    return StateChangeDirective(
        source="disease_progression",
        changes=changes,
        reason=f"{archetype_name}_day{day}",
    )


def _interpolate(trajectory: dict[int, float], day: int) -> float:
    """Linearly interpolate between defined day points."""
    days = sorted(trajectory.keys())

    if day <= days[0]:
        return trajectory[days[0]]
    if day >= days[-1]:
        return trajectory[days[-1]]

    # Find surrounding points
    for i in range(len(days) - 1):
        if days[i] <= day <= days[i + 1]:
            d0, d1 = days[i], days[i + 1]
            v0, v1 = trajectory[d0], trajectory[d1]
            frac = (day - d0) / (d1 - d0)
            return v0 + (v1 - v0) * frac

    return trajectory[days[-1]]
