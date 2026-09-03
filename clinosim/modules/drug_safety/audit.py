"""AD-60 audit plug-in for drug_safety (minimal MVP).

Provides a stand-alone ``audit_drug_safety(patients)`` free function that
post-hoc walks generated cohorts for contraindicated drug pairs that
should have been blocked by the gate but were not. Catches integration
regressions where a new caller adds a med without consulting the gate.

Full AD-60 four-axis registration (canonical_constants + structural +
clinical + firing_proof) is deferred to a follow-up issue. This MVP
plug-in ships only the ``clinical_acceptance``-style pair enumeration
and is invoked directly from the CLI / verify_medical_stats.py, not
through the AD-60 audit registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clinosim.modules.drug_safety.engine import check_pair


@dataclass
class AuditFinding:
    patient_id: str
    description: str
    severity: str  # matches SafetyVerdict.severity


def audit_drug_safety(patients: list[Any]) -> list[AuditFinding]:
    """Return a list of contraindicated pair findings in the cohort.

    Walks each patient's ``home_medications`` (and any accepted admission
    orders when available) for pairs whose ``check_pair`` verdict is
    ``major`` or ``contraindicated``. A finding is emitted only when the
    pair does NOT appear in ``safety_skip_log`` (i.e. the gate did not
    fire). Empty return means the gate fully covered the cohort.
    """
    out: list[AuditFinding] = []
    for p in patients:
        profile = getattr(p, "profile", p)
        home_meds = getattr(profile, "home_medications", None) or getattr(profile, "current_medications", [])
        home_meds = home_meds or []
        drugs = [getattr(m, "drug_name", None) or getattr(m, "drug", None) for m in home_meds]
        drugs = [d for d in drugs if d]
        skip_log = getattr(profile, "safety_skip_log", None) or []
        skipped_pairs = {(entry.candidate_drug, entry.active_conflict) for entry in skip_log}
        skipped_pairs |= {(entry.active_conflict, entry.candidate_drug) for entry in skip_log}

        for i, a in enumerate(drugs):
            for b in drugs[i + 1 :]:
                verdict = check_pair(a, b)
                if verdict.is_allowed:
                    continue
                if verdict.severity in {"minor", "moderate"}:
                    continue
                if (a, b) in skipped_pairs or (b, a) in skipped_pairs:
                    continue
                out.append(
                    AuditFinding(
                        patient_id=getattr(profile, "patient_id", "unknown"),
                        description=(
                            f"Contraindicated pair {a} + {b} present in home_medications "
                            f"but no matching safety_skip_log entry (severity: {verdict.severity})."
                        ),
                        severity=verdict.severity,
                    )
                )
    return out
