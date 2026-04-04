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


@dataclass
class ConditionEvent:
    """What actually happens to the patient (hidden ground truth). AD-28.

    This is the TRUE cause of the patient's condition, which may or may not
    be correctly identified by the clinical process.
    """

    condition_id: str = ""
    condition_type: str = "known_disease"  # "known_disease" | "mixed" | "unknown"

    # For known_disease / mixed: the actual diseases driving state changes
    ground_truth_diseases: list[str] = field(default_factory=list)

    # For unknown: the symptom pattern without identified cause
    symptom_pattern: str = ""  # "fever_unknown" | "weight_loss" | "malaise"

    # Combined state impact from all causes (applied to physiology)
    state_impacts: dict[str, float] = field(default_factory=dict)

    # Presenting symptoms (what the patient reports)
    presenting_symptoms: list[dict] = field(default_factory=list)


@dataclass
class ClinicalDiagnosis:
    """What the hospital concludes (may differ from ground truth). AD-28.

    This is the diagnosis as recorded in the EHR — the clinical output,
    not the hidden truth.
    """

    admission_diagnosis_code: str = ""  # ICD at admission (often vague: R50.9, J18.9)
    admission_diagnosis_name: str = ""
    working_diagnoses: list[dict] = field(default_factory=list)  # [{code, name, day, confidence}]
    discharge_diagnosis_code: str = ""  # ICD at discharge
    discharge_diagnosis_name: str = ""

    # Hidden fields (in CIF, not in clinical output)
    diagnosis_correct: bool = True  # does discharge dx match ground truth?
    missed_diagnoses: list[str] = field(default_factory=list)  # ground truth not identified
    overcalled_diagnoses: list[str] = field(default_factory=list)  # diagnosed but not present


@dataclass
class DiagnosticAccuracyConfig:
    """Tunable diagnostic accuracy parameters. AD-29."""

    initial_correct_rate: float = 0.60  # first working dx matches truth
    final_correct_rate: float = 0.85  # discharge dx matches truth
    missed_secondary_rate: float = 0.30  # miss secondary dx in mixed cases
    fuo_rate: float = 0.05  # fever remains undiagnosed
    incidental_finding_rate: float = 0.08  # find unrelated condition
