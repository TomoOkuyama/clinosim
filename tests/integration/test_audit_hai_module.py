"""Integration test: real HAI audit plug-in registers and the engine
runs lift-firing proof + constants check end-to-end."""

from __future__ import annotations

import importlib

import pytest

from clinosim.audit.engine import AuditEngine
from clinosim.audit.registry import _reset_for_test


@pytest.fixture(autouse=True)
def _reset():
    _reset_for_test()
    importlib.reload(importlib.import_module("clinosim.modules.hai.audit"))
    yield
    _reset_for_test()


@pytest.mark.integration
def test_hai_audit_silent_no_op_passes_on_clean_lift(tmp_path):
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    engine = AuditEngine(cohort_dir=tmp_path, axes=["silent_no_op"])
    result = engine.run()
    sn_result = result.results.get(("silent_no_op", "hai"))
    assert sn_result is not None
    # Constants check + proof both PASS → overall PASS
    assert sn_result.status == "PASS", f"silent_no_op axis FAIL findings: {[f.message for f in sn_result.findings]}"


@pytest.mark.integration
def test_hai_audit_structural_na_on_empty_cohort(tmp_path):
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    engine = AuditEngine(cohort_dir=tmp_path, axes=["structural"])
    result = engine.run()
    structural_result = result.results.get(("structural", "hai"))
    assert structural_result is not None
    assert structural_result.status == "N/A"
