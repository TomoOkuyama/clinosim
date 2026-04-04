"""Diagnosis engine — v0.1-beta: Bayesian differential diagnosis.

Maintains a probability distribution over candidate diagnoses and
updates via likelihood ratios as test results arrive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DiagnosisCandidate:
    disease_code: str
    icd_code: str
    display_name: str
    probability: float
    evidence: list[str] = field(default_factory=list)


@dataclass
class DifferentialDiagnosis:
    candidates: list[DiagnosisCandidate] = field(default_factory=list)
    working_diagnosis: str | None = None
    confirmed: bool = False
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def top_candidate(self) -> DiagnosisCandidate | None:
        return self.candidates[0] if self.candidates else None


# Disease-specific differentials
DIFFERENTIALS: dict[str, list[dict]] = {
    "bacterial_pneumonia": [
        {"disease": "bacterial_pneumonia", "icd": "J18.9", "name": "Bacterial pneumonia", "prior": 0.45},
        {"disease": "viral_pneumonia", "icd": "J12.9", "name": "Viral pneumonia", "prior": 0.15},
        {"disease": "influenza", "icd": "J11.1", "name": "Influenza", "prior": 0.10},
        {"disease": "heart_failure", "icd": "I50.9", "name": "Heart failure (pulmonary edema)", "prior": 0.10},
        {"disease": "pulmonary_embolism", "icd": "I26.9", "name": "Pulmonary embolism", "prior": 0.05},
        {"disease": "tuberculosis", "icd": "A15.0", "name": "Tuberculosis", "prior": 0.02},
        {"disease": "other", "icd": "R05", "name": "Other respiratory", "prior": 0.13},
    ],
    "heart_failure_exacerbation": [
        {"disease": "heart_failure_exacerbation", "icd": "I50.9", "name": "Heart failure exacerbation", "prior": 0.55},
        {"disease": "pneumonia", "icd": "J18.9", "name": "Pneumonia", "prior": 0.15},
        {"disease": "acute_coronary_syndrome", "icd": "I21.9", "name": "Acute coronary syndrome", "prior": 0.10},
        {"disease": "pulmonary_embolism", "icd": "I26.9", "name": "Pulmonary embolism", "prior": 0.05},
        {"disease": "copd_exacerbation", "icd": "J44.1", "name": "COPD exacerbation", "prior": 0.05},
        {"disease": "other", "icd": "R06.0", "name": "Other dyspnea", "prior": 0.10},
    ],
    "hip_fracture": [
        {"disease": "hip_fracture", "icd": "S72.0", "name": "Hip fracture", "prior": 0.85},
        {"disease": "pathological_fracture", "icd": "M84.4", "name": "Pathological fracture (tumor)", "prior": 0.05},
        {"disease": "pelvic_fracture", "icd": "S32.1", "name": "Pelvic fracture", "prior": 0.05},
        {"disease": "other", "icd": "M79.6", "name": "Other hip pain", "prior": 0.05},
    ],
}

# Diagnosis code progression (more specific as confidence grows)
DIAGNOSIS_PROGRESSION: dict[str, list[tuple[float, str, str]]] = {
    "bacterial_pneumonia": [
        (0.0, "J18.9", "Pneumonia, unspecified"),
        (0.7, "J18.1", "Lobar pneumonia, unspecified"),
        (0.9, "J13", "Pneumonia due to Streptococcus pneumoniae"),
    ],
    "heart_failure_exacerbation": [
        (0.0, "I50.9", "Heart failure, unspecified"),
        (0.7, "I50.0", "Congestive heart failure"),
        (0.9, "I50.0", "Congestive heart failure, acute exacerbation"),
    ],
    "hip_fracture": [
        (0.0, "S72.0", "Fracture of neck of femur"),
        (0.7, "S72.00", "Fracture of neck of femur, closed"),
        (0.9, "S72.00", "Fracture of neck of femur, closed"),
    ],
}

# Keep backward compatibility
DEFAULT_PNEUMONIA_DIFFERENTIAL = DIFFERENTIALS["bacterial_pneumonia"]

# Likelihood ratios for key findings
LR_TABLE: dict[str, dict[str, dict[str, float]]] = {
    "chest_xray_consolidation": {
        "bacterial_pneumonia": {"pos": 8.0, "neg": 0.3},
        "viral_pneumonia": {"pos": 2.0, "neg": 0.7},
        "heart_failure": {"pos": 0.5, "neg": 1.1},
    },
    "procalcitonin_elevated": {
        "bacterial_pneumonia": {"pos": 6.0, "neg": 0.15},
        "viral_pneumonia": {"pos": 0.3, "neg": 2.0},
    },
    "crp_above_100": {
        "bacterial_pneumonia": {"pos": 3.5, "neg": 0.4},
        "viral_pneumonia": {"pos": 0.5, "neg": 1.5},
    },
    "wbc_elevated": {
        "bacterial_pneumonia": {"pos": 2.5, "neg": 0.6},
        "viral_pneumonia": {"pos": 0.5, "neg": 1.3},
    },
}

def initialize_differential(
    disease_id: str = "bacterial_pneumonia",
    age: int = 70,
) -> DifferentialDiagnosis:
    """Create initial differential from disease-specific priors, adjusted by age."""
    differential_list = DIFFERENTIALS.get(disease_id, DEFAULT_PNEUMONIA_DIFFERENTIAL)
    candidates = []
    for dx in differential_list:
        prior = dx["prior"]
        # Age adjustment: elderly → higher probability of HF overlap
        if age >= 75 and dx["disease"] == "heart_failure":
            prior *= 1.5
        candidates.append(DiagnosisCandidate(
            disease_code=dx["disease"],
            icd_code=dx["icd"],
            display_name=dx["name"],
            probability=prior,
        ))

    # Normalize
    total = sum(c.probability for c in candidates)
    for c in candidates:
        c.probability /= total

    candidates.sort(key=lambda c: -c.probability)

    diff = DifferentialDiagnosis(candidates=candidates)
    if candidates[0].probability > 0.5:
        diff.working_diagnosis = candidates[0].disease_code
    return diff


def update_differential(
    diff: DifferentialDiagnosis,
    findings: list[tuple[str, bool]],
    confirmation_threshold: float = 0.90,
) -> DifferentialDiagnosis:
    """Update differential with new findings via Bayesian update.

    Args:
        diff: Current differential
        findings: List of (finding_name, is_positive) tuples
        confirmation_threshold: Probability at which diagnosis is confirmed
    """
    for finding_name, is_positive in findings:
        lr_entry = LR_TABLE.get(finding_name)
        if lr_entry is None:
            continue

        for candidate in diff.candidates:
            dx = candidate.disease_code
            if dx in lr_entry:
                lr = lr_entry[dx]["pos" if is_positive else "neg"]
                candidate.probability *= lr
                candidate.evidence.append(
                    f"{finding_name}: {'(+)' if is_positive else '(-)'} LR={lr}"
                )

    # Normalize
    total = sum(c.probability for c in diff.candidates)
    if total > 0:
        for c in diff.candidates:
            c.probability /= total

    # Sort
    diff.candidates.sort(key=lambda c: -c.probability)

    # Check confirmation
    top = diff.candidates[0]
    if top.probability >= confirmation_threshold:
        diff.confirmed = True
        diff.working_diagnosis = top.disease_code
    elif top.probability >= 0.5:
        diff.working_diagnosis = top.disease_code

    diff.timestamp = datetime.now()
    return diff


def get_current_diagnosis_code(diff: DifferentialDiagnosis) -> tuple[str, str]:
    """Returns (ICD code, display name) based on current confidence."""
    if not diff.working_diagnosis:
        return "R05", "Cough, unspecified"

    progression = DIAGNOSIS_PROGRESSION.get(diff.working_diagnosis)
    if not progression:
        top = diff.top_candidate
        return (top.icd_code, top.display_name) if top else ("R05", "Cough")

    confidence = diff.top_candidate.probability if diff.top_candidate else 0
    code, name = progression[0][1], progression[0][2]
    for threshold, c, n in progression:
        if confidence >= threshold:
            code, name = c, n
    return code, name
