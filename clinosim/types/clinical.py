"""Clinical state types — physiological state, state changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PhysiologicalState:
    """Snapshot of all hidden state variables at a point in time."""

    timestamp: datetime = field(default_factory=datetime.now)
    patient_id: str = ""

    inflammation_level: float = 0.03  # 0.0–1.0
    renal_function: float = 1.0  # 0.0–1.0
    cardiac_function: float = 1.0  # 0.0–1.0
    hepatic_function: float = 1.0  # 0.0–1.0
    anemia_level: float = 0.0  # 0.0–1.0
    coagulation_status: float = 0.0  # 0.0–1.0
    volume_status: float = 0.0  # -1.0–+1.0
    perfusion_status: float = 1.0  # 0.0–1.0
    ph_status: float = 0.0  # -1.0–+1.0


@dataclass
class StateChangeDirective:
    """Instruction to update physiological state variables."""

    timestamp: datetime = field(default_factory=datetime.now)
    patient_id: str = ""
    source: str = ""  # "disease_progression" | "treatment_effect" | "complication"
    changes: dict[str, float] = field(default_factory=dict)
    reason: str = ""
