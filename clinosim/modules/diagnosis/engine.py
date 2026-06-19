"""Diagnosis engine — v0.1-beta: Bayesian differential diagnosis.

Maintains a probability distribution over candidate diagnoses and
updates via likelihood ratios as test results arrive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from clinosim.codes import lookup

_REFERENCE_DATA = Path(__file__).parent / "reference_data" / "builtin_differentials.yaml"


def _load_reference_data() -> tuple[
    dict[str, list[dict[str, object]]],
    dict[str, list[tuple[float, str]]],
    dict[str, dict[str, dict[str, float]]],
]:
    """Load built-in differential tables from YAML (AD-18 internal reference table).

    Display names are not stored; they are resolved at use time via clinosim.codes.
    """
    with open(_REFERENCE_DATA) as f:
        data = yaml.safe_load(f) or {}
    differentials = data.get("differentials", {})
    progression = {
        dx: [(float(row[0]), str(row[1])) for row in rows]
        for dx, rows in data.get("diagnosis_progression", {}).items()
    }
    lr_table = data.get("lr_table", {})
    # Sanity: every differential entry must carry disease/icd/prior
    for dx, rows in differentials.items():
        for e in rows:
            if not {"disease", "icd", "prior"} <= e.keys():
                raise ValueError(f"builtin_differentials.yaml: bad entry in {dx!r}: {e!r}")
    return differentials, progression, lr_table


def _display(icd_code: str) -> str:
    """Resolve an ICD code's English display via the code system (AD-30)."""
    return lookup("icd-10-cm", icd_code, "en")


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


DIFFERENTIALS, DIAGNOSIS_PROGRESSION, LR_TABLE = _load_reference_data()

# Keep backward compatibility
DEFAULT_PNEUMONIA_DIFFERENTIAL = DIFFERENTIALS["bacterial_pneumonia"]


def initialize_differential(
    disease_id: str = "bacterial_pneumonia",
    age: int = 70,
    protocol_diagnostic: dict | None = None,
) -> DifferentialDiagnosis:
    """Create initial differential. Uses protocol YAML data if provided, falls back to built-in.

    Args:
        protocol_diagnostic: The 'diagnostic' section from disease YAML.
            If provided, uses protocol_diagnostic['differential'] and
            protocol_diagnostic['diagnosis_progression'].
    """
    # Prefer protocol YAML data, fall back to built-in
    if protocol_diagnostic and "differential" in protocol_diagnostic:
        differential_list = protocol_diagnostic["differential"]
    else:
        differential_list = DIFFERENTIALS.get(disease_id, DEFAULT_PNEUMONIA_DIFFERENTIAL)
    candidates = []
    for dx in differential_list:
        prior = dx["prior"]
        # Age adjustment: elderly → higher probability of HF overlap
        if age >= 75 and dx["disease"] == "heart_failure":
            prior *= 1.5
        candidates.append(
            DiagnosisCandidate(
                disease_code=dx["disease"],
                icd_code=dx["icd"],
                display_name=_display(dx["icd"]),
                probability=prior,
            )
        )

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
    protocol_lr_table: dict | None = None,
) -> DifferentialDiagnosis:
    """Update differential with new findings via Bayesian update.

    Args:
        diff: Current differential
        protocol_lr_table: LR table from disease YAML. Falls back to built-in LR_TABLE.
        findings: List of (finding_name, is_positive) tuples
        confirmation_threshold: Probability at which diagnosis is confirmed
    """
    for finding_name, is_positive in findings:
        effective_lr = protocol_lr_table or LR_TABLE
        lr_entry = effective_lr.get(finding_name)
        if lr_entry is None:
            continue

        for candidate in diff.candidates:
            dx = candidate.disease_code
            if dx in lr_entry:
                dx_lr = lr_entry[dx]
                if is_positive:
                    lr = dx_lr.get("pos", dx_lr.get("positive_LR", 1.0))
                else:
                    lr = dx_lr.get("neg", dx_lr.get("negative_LR", 1.0))
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


def get_current_diagnosis_code(
    diff: DifferentialDiagnosis,
    protocol_progression: dict | None = None,
) -> tuple[str, str]:
    """Returns (ICD code, display name) based on current confidence.

    Strategy:
    1. Use working_diagnosis if set (high confidence)
    2. Fall back to top candidate (any confidence)
    3. Last resort: R69 (Illness, unspecified)
    """
    # Determine the target disease — fall back to top candidate if no working dx
    target = diff.working_diagnosis
    if not target and diff.candidates:
        target = diff.candidates[0].disease_code

    if not target:
        return "R69", "Illness, unspecified"

    # Look up progression (YAML > built-in)
    progression = None
    if protocol_progression and target in protocol_progression:
        progression = protocol_progression[target]
    else:
        progression = DIAGNOSIS_PROGRESSION.get(target)

    if not progression:
        # No progression — fall back to top candidate's icd_code
        top = diff.top_candidate
        if top and top.icd_code:
            return (top.icd_code, _display(top.icd_code))
        return "R69", "Illness, unspecified"

    confidence = diff.candidates[0].probability if diff.candidates else 0
    code = progression[0][1]
    for row in progression:
        if confidence >= row[0]:
            code = row[1]
    return code, _display(code)
