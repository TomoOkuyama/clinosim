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
    register_audit_module(
        ModuleAuditSpec(
            name="hai",
            structural_obs_codes={"WBC": ("6690-2",)},
        )
    )
    engine = AuditEngine(cohort_dir=_empty_cohort(tmp_path))
    result = engine.run()
    assert sorted(result.axes) == sorted(_BUILTIN_AXES)
    assert "hai" in result.modules


@pytest.mark.unit
def test_engine_module_filter(tmp_path: Path):
    register_audit_module(ModuleAuditSpec(name="hai"))
    register_audit_module(ModuleAuditSpec(name="device"))
    # Restrict axes to per-module ones so the cohort-level sentinel
    # (added when jp_language runs) does not confound the filter test.
    engine = AuditEngine(
        cohort_dir=_empty_cohort(tmp_path),
        modules=["hai"],
        axes=["structural", "silent_no_op"],
    )
    result = engine.run()
    assert result.modules == ["hai"]


@pytest.mark.unit
def test_engine_cohort_axis_adds_sentinel_module(tmp_path: Path):
    """jp_language is a cohort-level axis (#473): it runs once with
    ``spec=None`` and its result is attached to the synthetic
    ``_cohort_`` module row so the reporter grid can render it."""
    register_audit_module(ModuleAuditSpec(name="hai"))
    engine = AuditEngine(cohort_dir=_empty_cohort(tmp_path), axes=["jp_language"])
    result = engine.run()
    # ``discover()`` re-imports every ``modules/*/audit.py`` so the
    # exact module list depends on registered specs. The invariant we
    # pin: the sentinel is present, and no per-registered-module
    # jp_language result exists.
    assert "_cohort_" in result.modules
    assert ("jp_language", "_cohort_") in result.results
    # Per-module keys MUST NOT be created for cohort-level axes.
    for mod in result.modules:
        if mod == "_cohort_":
            continue
        assert ("jp_language", mod) not in result.results


@pytest.mark.unit
def test_engine_cohort_axis_runs_once_regardless_of_module_count(tmp_path: Path):
    register_audit_module(ModuleAuditSpec(name="hai"))
    register_audit_module(ModuleAuditSpec(name="device"))
    engine = AuditEngine(cohort_dir=_empty_cohort(tmp_path), axes=["jp_language"])
    result = engine.run()
    # Exactly one cohort-level result exists, not one per module.
    jp_keys = [k for k in result.results if k[0] == "jp_language"]
    assert jp_keys == [("jp_language", "_cohort_")]


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
