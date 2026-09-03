"""clinosim.modules.drug_safety — contraindication gate + alternative substitution.

See docs/superpowers/specs/2026-09-03-drug-safety-module-design.md for design.
"""

from clinosim.modules.drug_safety.verdict import (
    SEVERITY_RANK,
    SafetySkipEntry,
    SafetyVerdict,
    Severity,
)

__all__ = ["SafetyVerdict", "SafetySkipEntry", "Severity", "SEVERITY_RANK"]
