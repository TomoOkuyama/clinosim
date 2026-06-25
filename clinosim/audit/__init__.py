"""clinosim audit framework — unified verification gate.

See docs/superpowers/specs/2026-06-25-dqr-framework-strengthening-design.md
for the design rationale. Public exports:
- ModuleAuditSpec: the per-Module contract
- register_audit_module: invoked by modules/<name>/audit.py
- Severity, AuditFinding, AxisResult, AuditResult: result types
- Cohort: lazy NDJSON reader
"""

from clinosim.audit.registry import (
    ModuleAuditSpec,
    register_audit_module,
)
from clinosim.audit.types import (
    AuditFinding,
    AuditResult,
    AxisResult,
    Cohort,
    Severity,
)

__all__ = [
    "ModuleAuditSpec",
    "register_audit_module",
    "AuditFinding",
    "AuditResult",
    "AxisResult",
    "Cohort",
    "Severity",
]
