"""clinosim.modules.drug_safety — contraindication gate + alternative substitution.

See docs/superpowers/specs/2026-09-03-drug-safety-module-design.md for design.
"""

from clinosim.modules.drug_safety.classifier import (
    canonical_name,
    japanese_display,
    resolve_classes,
)
from clinosim.modules.drug_safety.engine import (
    AlternativeDrug,
    check_candidate_against_active,
    check_pair,
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
    "SafetySkipEntry",
    "SafetyVerdict",
    "Severity",
    "canonical_name",
    "check_candidate_against_active",
    "check_pair",
    "japanese_display",
    "resolve_classes",
    "suggest_alternative",
]
