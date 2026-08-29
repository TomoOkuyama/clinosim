"""Diagnosis engine — v0.1-beta: Bayesian differential diagnosis.

Maintains a probability distribution over candidate diagnoses and
updates via likelihood ratios as test results arrive.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from clinosim.codes import lookup
from clinosim.modules.diagnosis._diagnosis_thresholds import (
    DEFAULT_CONFIRMATION_THRESHOLD,
    ELDERLY_HF_PRIOR_AGE_THRESHOLD,
    ELDERLY_HF_PRIOR_MULTIPLIER,
    NEUTRAL_LIKELIHOOD_RATIO,
    WORKING_DIAGNOSIS_MIN_PROB,
)
from clinosim.modules.diagnosis.nonspecific_codes import UNRESOLVED_DIAGNOSIS_ICD
from clinosim.types.diagnosis import DiagnosisCandidate, DifferentialDiagnosis

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


def _load_reference_data() -> tuple[
    dict[str, list[dict[str, object]]],
    dict[str, list[tuple[float, str]]],
    dict[str, dict[str, dict[str, float]]],
]:
    """Load built-in differential tables from YAML (AD-18 internal reference table).

    Display names are not stored; they are resolved at use time via clinosim.codes.
    """
    with open(_REF_DIR / "builtin_differentials.yaml") as f:
        data = yaml.safe_load(f) or {}
    differentials = data.get("differentials", {})
    progression = {
        dx: [(float(row[0]), str(row[1])) for row in rows] for dx, rows in data.get("diagnosis_progression", {}).items()
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
        if age >= ELDERLY_HF_PRIOR_AGE_THRESHOLD and dx["disease"] == "heart_failure":
            prior *= ELDERLY_HF_PRIOR_MULTIPLIER
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
    if candidates[0].probability > WORKING_DIAGNOSIS_MIN_PROB:
        diff.working_diagnosis = candidates[0].disease_code
    return diff


def update_differential(
    diff: DifferentialDiagnosis,
    findings: list[tuple[str, bool]],
    confirmation_threshold: float = DEFAULT_CONFIRMATION_THRESHOLD,
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
                    lr = dx_lr.get("pos", dx_lr.get("positive_LR", NEUTRAL_LIKELIHOOD_RATIO))
                else:
                    lr = dx_lr.get("neg", dx_lr.get("negative_LR", NEUTRAL_LIKELIHOOD_RATIO))
                candidate.probability *= lr
                candidate.evidence.append(f"{finding_name}: {'(+)' if is_positive else '(-)'} LR={lr}")

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
    elif top.probability >= WORKING_DIAGNOSIS_MIN_PROB:
        diff.working_diagnosis = top.disease_code

    return diff


def get_current_diagnosis_code(
    diff: DifferentialDiagnosis,
    protocol_progression: dict | None = None,
    patient_sex: str | None = None,
) -> tuple[str, str]:
    """Returns (ICD code, display name) based on current confidence.

    Strategy:
    1. Use working_diagnosis if set (high confidence)
    2. Fall back to top candidate (any confidence)
    3. Last resort: R69 (Illness, unspecified)

    Issue #947 — sex-gated dispatch. When ``patient_sex`` is provided
    (``"M"`` / ``"F"`` from ``PatientProfile.sex``; ``"male"`` / ``"female"``
    from FHIR ``Patient.gender`` are also accepted), a candidate whose ICD
    is anatomy-locked to the opposite sex is skipped in favor of the next
    ranked sex-compatible candidate. The candidate list is already sorted
    by probability so this walk consumes no RNG state (safe for cross-
    platform bit-reproducibility per memory
    ``feedback_deterministic_rng_proxy_pattern``). Lock list lives at
    ``clinosim/locale/shared/icd10_sex_restrictions.yaml``.

    Falling back to the top (locked) code would emit an anatomically-
    impossible Condition — six such records were observed pre-fix
    (Issue #947). When every candidate is locked (should be rare and
    signals a wrong-disease dispatch upstream) we still return
    ``UNRESOLVED_DIAGNOSIS_ICD`` rather than a locked code.
    """
    # Sex-gate resolution: skip candidates whose ICD is anatomically
    # inappropriate for the patient's sex, then rebuild the target /
    # progression lookup on the first sex-compatible candidate.
    if patient_sex:
        # Import here to avoid an import cycle at engine load time
        # (sex_gating lives under clinosim.simulator).
        from clinosim.simulator.sex_gating import (
            is_sex_locked_for,
            pick_sex_compatible_dx_code,
        )
    else:
        is_sex_locked_for = None  # type: ignore[assignment]
        pick_sex_compatible_dx_code = None  # type: ignore[assignment]

    # Determine the target disease — fall back to top candidate if no working dx
    target = diff.working_diagnosis
    target_candidate = None
    if diff.candidates:
        # Prefer working_diagnosis if it is itself sex-compatible; otherwise
        # walk the ranked candidate list to the first sex-compatible one.
        if target:
            for c in diff.candidates:
                if c.disease_code == target:
                    target_candidate = c
                    break
        if patient_sex and target_candidate is not None:
            if is_sex_locked_for(target_candidate.icd_code, patient_sex):
                target_candidate = None
                target = None
        if target_candidate is None:
            if patient_sex:
                target_candidate = pick_sex_compatible_dx_code(diff.candidates, patient_sex)
            if target_candidate is None:
                target_candidate = diff.top_candidate
        if target_candidate is not None:
            target = target_candidate.disease_code

    if not target:
        return UNRESOLVED_DIAGNOSIS_ICD, _display(UNRESOLVED_DIAGNOSIS_ICD)

    # Look up progression (YAML > built-in)
    progression = None
    if protocol_progression and target in protocol_progression:
        progression = protocol_progression[target]
    else:
        progression = DIAGNOSIS_PROGRESSION.get(target)

    if not progression:
        # No progression — fall back to the resolved target candidate's icd_code.
        if target_candidate and target_candidate.icd_code:
            if patient_sex and is_sex_locked_for(target_candidate.icd_code, patient_sex):
                # Extremely rare: caller-provided sex conflicts with EVERY
                # ranked candidate. Emit unresolved rather than a locked code.
                return UNRESOLVED_DIAGNOSIS_ICD, _display(UNRESOLVED_DIAGNOSIS_ICD)
            return (target_candidate.icd_code, _display(target_candidate.icd_code))
        return UNRESOLVED_DIAGNOSIS_ICD, _display(UNRESOLVED_DIAGNOSIS_ICD)

    confidence = diff.candidates[0].probability if diff.candidates else 0
    code = progression[0][1]
    for row in progression:
        if confidence >= row[0]:
            code = row[1]
    # Progression codes are typically same-disease severity/certainty
    # variants of the resolved candidate's ICD (e.g. N39.0 → N39.9). If the
    # progression code is itself sex-locked for this patient, fall back to
    # the target candidate's own ICD (which was already sex-gated above);
    # if that is also locked, emit unresolved.
    if patient_sex and is_sex_locked_for(code, patient_sex):
        if (
            target_candidate
            and target_candidate.icd_code
            and not is_sex_locked_for(target_candidate.icd_code, patient_sex)
        ):
            return (target_candidate.icd_code, _display(target_candidate.icd_code))
        return UNRESOLVED_DIAGNOSIS_ICD, _display(UNRESOLVED_DIAGNOSIS_ICD)
    return code, _display(code)
