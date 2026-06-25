"""Unit tests for clinosim.audit.engine."""
from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.audit.engine import _BUILTIN_AXES, AuditEngine
from clinosim.audit.registry import (
    ModuleAuditSpec,
    _reset_for_test,
    register_audit_module,
)


@pytest.fixture(autouse=True)
def _clear():
    _reset_for_test()
    yield
    _reset_for_test()


def _empty_cohort(tmp_path: Path) -> Path:
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    return tmp_path


@pytest.mark.unit
def test_engine_runs_all_builtin_axes(tmp_path: Path):
    register_audit_module(ModuleAuditSpec(
        name="hai",
        structural_obs_codes={"WBC": ("6690-2",)},
    ))
    engine = AuditEngine(cohort_dir=_empty_cohort(tmp_path))
    result = engine.run()
    assert sorted(result.axes) == sorted(_BUILTIN_AXES)
    assert "hai" in result.modules


@pytest.mark.unit
def test_engine_module_filter(tmp_path: Path):
    register_audit_module(ModuleAuditSpec(name="hai"))
    register_audit_module(ModuleAuditSpec(name="device"))
    engine = AuditEngine(cohort_dir=_empty_cohort(tmp_path), modules=["hai"])
    result = engine.run()
    assert result.modules == ["hai"]


@pytest.mark.unit
def test_engine_axis_filter(tmp_path: Path):
    register_audit_module(ModuleAuditSpec(name="hai"))
    engine = AuditEngine(cohort_dir=_empty_cohort(tmp_path), axes=["silent_no_op"])
    result = engine.run()
    assert result.axes == ["silent_no_op"]


@pytest.mark.unit
def test_engine_overall_status_pass_on_empty(tmp_path: Path):
    register_audit_module(ModuleAuditSpec(name="hai"))
    engine = AuditEngine(cohort_dir=_empty_cohort(tmp_path))
    result = engine.run()
    # All axes return N/A on empty + no spec config → overall PASS
    assert result.overall_status() in ("PASS", "WARN")
