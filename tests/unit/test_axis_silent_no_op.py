"""Unit tests for clinosim.audit.axes.silent_no_op."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from clinosim.audit.axes import silent_no_op
from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import Cohort


def _proof_factory_pass():
    """Lift-firing proof builder that returns a record + apply_fn that
    bumps wbc_obs.value by exactly the expected delta."""
    wbc_obs = SimpleNamespace(value=11760.0, lab_name="WBC")

    def apply_fn(record, encounter, state_history, admission_time):
        wbc_obs.value = 14280.0
        return 1

    return {
        "record": SimpleNamespace(), "encounter": SimpleNamespace(),
        "state_history": [], "admission_time": None,
        "apply_fn": apply_fn,
        "expected": [(wbc_obs, 11760.0, 2520.0)],
    }


def _proof_factory_silent_no_op():
    wbc_obs = SimpleNamespace(value=11760.0, lab_name="WBC")

    def apply_fn(record, encounter, state_history, admission_time):
        return 0  # silently no-op

    return {
        "record": SimpleNamespace(), "encounter": SimpleNamespace(),
        "state_history": [], "admission_time": None,
        "apply_fn": apply_fn,
        "expected": [(wbc_obs, 11760.0, 2520.0)],
    }


@pytest.mark.unit
def test_silent_no_op_pass_with_proof(tmp_path: Path):
    spec = ModuleAuditSpec(
        name="hai",
        canonical_constants={"hai_type": ("clabsi", "cauti", "vap")},
        lift_firing_proof=_proof_factory_pass,
    )
    result = silent_no_op.run(spec, Cohort.open(tmp_path))
    assert result.status == "PASS"


@pytest.mark.unit
def test_silent_no_op_fail_when_proof_delta_mismatch(tmp_path: Path):
    spec = ModuleAuditSpec(
        name="hai", lift_firing_proof=_proof_factory_silent_no_op,
    )
    result = silent_no_op.run(spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("proof" in f.message.lower() for f in result.findings)


@pytest.mark.unit
def test_silent_no_op_constants_drift_yaml(tmp_path: Path):
    yaml_file = tmp_path / "modules/hai/reference_data/hai_lab_lift.yaml"
    yaml_file.parent.mkdir(parents=True)
    yaml_file.write_text(
        "ramp_peak_days: 2\nhai_lift:\n  CLABSI: 0.35\n",  # UPPERCASE = drift
        encoding="utf-8",
    )
    spec = ModuleAuditSpec(
        name="hai",
        canonical_constants={"hai_type": ("clabsi", "cauti", "vap")},
        yaml_keys_to_validate={
            str(yaml_file): ("hai_lift",),
        },
    )
    result = silent_no_op.run(spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("CLABSI" in f.message or "drift" in f.message.lower() for f in result.findings)


@pytest.mark.unit
def test_silent_no_op_na_when_no_checks(tmp_path: Path):
    # No constants files + no proof → axis runs but produces no info/findings
    spec = ModuleAuditSpec(name="hai")
    result = silent_no_op.run(spec, Cohort.open(tmp_path))
    assert result.status == "N/A"
