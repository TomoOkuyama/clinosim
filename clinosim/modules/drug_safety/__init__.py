"""clinosim.modules.drug_safety — contraindication gate + alternative substitution.

See docs/superpowers/specs/2026-09-03-drug-safety-module-design.md for design.
"""

from clinosim.modules.drug_safety.classifier import (
    canonical_name,
    japanese_display,
    resolve_classes,
)
from clinosim.modules.drug_safety.demographic import (
    DemographicVerdict,
    check_demographic_gate,
)
from clinosim.modules.drug_safety.engine import (
    AlternativeDrug,
    allergy_entries,
    allergy_skip_verdict,
    check_candidate_against_active,
    check_candidate_against_allergies,
    check_candidate_against_disease_state,
    check_pair,
    condition_entries,
    conflict_display,
    discharge_reconciliation_rules,
    rule_kind,
    suggest_alternative,
)
from clinosim.modules.drug_safety.verdict import (
    SEVERITY_RANK,
    SafetySkipEntry,
    SafetyVerdict,
    Severity,
)

__all__ = [
    "SEVERITY_RANK",
    "AlternativeDrug",
    "DemographicVerdict",
    "SafetySkipEntry",
    "SafetyVerdict",
    "Severity",
    "allergy_entries",
    "allergy_skip_verdict",
    "canonical_name",
    "check_candidate_against_active",
    "check_candidate_against_allergies",
    "check_candidate_against_disease_state",
    "check_demographic_gate",
    "check_pair",
    "condition_entries",
    "conflict_display",
    "discharge_reconciliation_rules",
    "japanese_display",
    "resolve_classes",
    "rule_kind",
    "suggest_alternative",
]
