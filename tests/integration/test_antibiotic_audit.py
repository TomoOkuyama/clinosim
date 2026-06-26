"""Integration: clinosim audit framework discovers + accepts the antibiotic module.

PR-93 follow-up (adversarial review fix): also verifies that the
silent_no_op axis actually consumes the proof (the original PR-93
returned a plain dict that the axis silently skipped without raising
— PR-90 class bug in the audit harness itself).
"""
from datetime import datetime

import pytest

from clinosim.audit.axes.silent_no_op import _check_proof
from clinosim.audit.registry import discover, get_registered
from clinosim.audit.types import AxisResult, Severity


@pytest.mark.integration
def test_antibiotic_module_registered():
    discover()
    assert "antibiotic" in get_registered()


@pytest.mark.integration
def test_antibiotic_proof_factory_returns_equality_checks():
    """The proof factory must return the equality_checks proof format."""
    discover()
    spec = get_registered()["antibiotic"]
    assert spec.lift_firing_proof is not None
    proof = spec.lift_firing_proof()
    assert "equality_checks" in proof, (
        "antibiotic proof must use the equality_checks format (PR-93 fix); "
        "the original dict-of-actuals-and-'expected'-dict format is silently "
        "skipped by the silent_no_op axis"
    )
    # Spot-check a couple of canonical checks
    labels = {label for label, _, _ in proof["equality_checks"]}
    assert "ext_antibiotic_count" in labels
    assert "mar_count" in labels
    assert "mar_first_dt" in labels


@pytest.mark.integration
def test_antibiotic_silent_no_op_axis_actually_runs_proof():
    """The silent_no_op axis must CONSUME the proof and report PASS findings.

    PR-93 adversarial review surfaced that the original antibiotic proof
    returned a plain dict the axis silently skipped (apply_fn was None,
    expected was not list-of-tuples). The axis fix recognises the new
    equality_checks format and runs each check.

    This test pins both halves: the axis recognises the format AND each
    equality check passes (closed-form Ceftriaxone q24h × 7d).
    """
    discover()
    spec = get_registered()["antibiotic"]
    result = AxisResult(axis="silent_no_op", module="antibiotic")
    _check_proof(spec, result)
    # No FAIL findings — every equality check must match
    fails = [f for f in result.findings if f.severity == Severity.FAIL]
    assert not fails, f"silent_no_op axis reported FAIL findings: {fails!r}"
    # Each equality_check produces an info entry — ensure non-empty
    eq_info_keys = [k for k in result.info if k.startswith("proof_eq_")]
    assert eq_info_keys, (
        "silent_no_op axis did not consume any equality_checks — "
        "the axis is silently no-op'ing the antibiotic proof"
    )


@pytest.mark.integration
def test_silent_no_op_axis_fails_on_stub_proof():
    """A proof returning neither format must FAIL (audit-harness self-check).

    Prevents PR-93 class regression: a future module that returns a plain
    dict (no apply_fn, no equality_checks) was silently skipped before this
    fix. Now the axis records a FAIL finding.
    """
    from clinosim.audit.registry import ModuleAuditSpec
    stub_spec = ModuleAuditSpec(
        name="stub",
        lift_firing_proof=lambda: {"some_actual": 1, "expected": {"some_actual": 1}},
    )
    result = AxisResult(axis="silent_no_op", module="stub")
    _check_proof(stub_spec, result)
    fails = [f for f in result.findings if f.severity == Severity.FAIL]
    assert any("no-op silent skip" in f.message for f in fails), (
        "axis must FAIL when proof has no recognised format"
    )


@pytest.mark.integration
def test_silent_no_op_axis_fails_on_equality_mismatch():
    """A proof whose equality_checks reports actual != expected must FAIL."""
    from clinosim.audit.registry import ModuleAuditSpec
    bad_spec = ModuleAuditSpec(
        name="bad",
        lift_firing_proof=lambda: {
            "equality_checks": [("count", 0, 1)],   # actual=0, expected=1
        },
    )
    result = AxisResult(axis="silent_no_op", module="bad")
    _check_proof(bad_spec, result)
    fails = [f for f in result.findings if f.severity == Severity.FAIL]
    assert any("equality_check 'count'" in f.message for f in fails)
