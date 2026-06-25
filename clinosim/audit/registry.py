"""Audit-framework module registry + discovery.

ModuleAuditSpec is the per-Module contract; modules/<name>/audit.py
side-effect-imports register_audit_module(spec) at import time. The
audit engine calls discover() before iterating registered modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ModuleAuditSpec:
    name: str
    canonical_constants: dict[str, tuple[str, ...]] = field(default_factory=dict)
    yaml_keys_to_validate: dict[str, tuple[str, ...]] = field(default_factory=dict)
    cohort_filter: Callable | None = None
    per_event_check: dict[str, Callable] = field(default_factory=dict)
    lift_firing_proof: Callable | None = None
    structural_obs_codes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    clinical_acceptance: dict[str, dict[str, float]] = field(default_factory=dict)


_MODULES: dict[str, ModuleAuditSpec] = {}


def register_audit_module(spec: ModuleAuditSpec) -> None:
    """Register a per-Module audit. Last-wins on duplicate name."""
    _MODULES[spec.name] = spec


def get_registered() -> dict[str, ModuleAuditSpec]:
    """Return a shallow copy of the registry."""
    return dict(_MODULES)


def _reset_for_test() -> None:
    """Test-only: clear the registry between cases."""
    _MODULES.clear()


def discover() -> None:
    """Import every clinosim/modules/<name>/audit.py that exists.

    Each import side-effects register_audit_module(...). Modules with
    no audit.py are silently skipped. Repeated calls are idempotent
    (importlib caches; register_audit_module is last-wins).
    """
    from importlib import import_module
    from pathlib import Path

    modules_root = Path(__file__).parent.parent / "modules"
    for audit_file in sorted(modules_root.glob("*/audit.py")):
        module_name = audit_file.parent.name
        import_module(f"clinosim.modules.{module_name}.audit")
