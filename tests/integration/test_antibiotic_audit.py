"""Integration: clinosim audit framework discovers + accepts the antibiotic module.

PR-93 follow-up (adversarial review fix): also verifies that the
silent_no_op axis actually consumes the proof (the original PR-93
returned a plain dict that the axis silently skipped without raising
— PR-90 class bug in the audit harness itself).
"""
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
    # Spot-check PR3b-1 canonical checks
    labels = {label for label, _, _ in proof["equality_checks"]}
    assert "ext_antibiotic_count" in labels
    assert "mar_count" in labels
    assert "mar_first_dt" in labels
    # PR3b-2 antibiogram checks — a broken proof returning [] would silently pass
    # without these assertions (PR-90 class silent no-op gate).
    assert "clabsi_saureus_susceptibility_count" in labels, (
        "PR3b-2 antibiogram count check missing — silent no-op"
    )
    assert "clabsi_saureus_vancomycin_is_S" in labels, (
        "PR3b-2 vancomycin-S check missing — silent no-op"
    )
    assert len(proof["equality_checks"]) == 17, (
        f"Expected 17 equality_checks (8 PR3b-1 + 3 PR3b-2 + 6 PR3b-3 "
        f"narrow chain), got {len(proof['equality_checks'])}"
    )


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
    # PR3b-2 specific info keys — a broken antibiogram proof returning []
    # would silently pass without these (PR-90 class silent no-op gate).
    assert "proof_eq_clabsi_saureus_susceptibility_count" in result.info, (
        "silent_no_op axis did not surface PR3b-2 count proof"
    )
    assert "proof_eq_clabsi_saureus_vancomycin_is_S" in result.info, (
        "silent_no_op axis did not surface PR3b-2 vancomycin proof"
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


@pytest.mark.integration
def test_lift_firing_proof_pr3b3_narrow_chain_six_checks_pass() -> None:
    """The combined proof now includes 6 PR3b-3 equality_checks: narrow target,
    each empirical discontinuation_datetime, narrowed regimen count, drug,
    intent. All 6 must pass under synthetic CLABSI/MSSA case."""
    from clinosim.modules.antibiotic.audit import _build_combined_proof

    proof = _build_combined_proof()
    labels = [label for label, _, _ in proof["equality_checks"]]
    pr3b3_labels = [l for l in labels if l.startswith("pr3b3_")]
    assert len(pr3b3_labels) == 6, (
        f"expected 6 pr3b3_* checks, got {len(pr3b3_labels)}: {pr3b3_labels}"
    )
    # Verify each check passes (actual == expected)
    for label, actual, expected in proof["equality_checks"]:
        if label.startswith("pr3b3_"):
            assert actual == expected, (
                f"{label}: actual={actual!r} != expected={expected!r}"
            )


@pytest.mark.integration
def test_clinical_axis_wires_pr3b3_gates_on_empty_cohort() -> None:
    """PR3b-3: smoke-verify clinical axis runs without crashing even with an
    empty cohort. Real population-scale gate firing is covered by the DQR
    (Task 8). This test guarantees the 3 new enforcement blocks (NHSN R-rate,
    empty rate, narrow rate) don't NPE on empty data."""
    import tempfile
    from pathlib import Path

    from clinosim.audit.axes import clinical as clinical_axis
    from clinosim.audit.types import Cohort

    discover()
    spec = get_registered()["antibiotic"]
    with tempfile.TemporaryDirectory() as tmp:
        cohort = Cohort(root=Path(tmp))
        result = clinical_axis.run(spec, cohort)
        # Axis must complete without raising; result is well-formed
        assert isinstance(result.findings, list)
        assert isinstance(result.info, dict)


@pytest.mark.integration
def test_audit_clinical_acceptance_has_narrow_rate_bands() -> None:
    """PR3b-3: narrow_rate_bands key surfaced in clinical_acceptance for
    Task 6 active enforcement."""
    discover()
    spec = get_registered()["antibiotic"]
    bands = spec.clinical_acceptance.get("narrow_rate_bands")
    assert bands is not None
    assert isinstance(bands, list)
    assert len(bands) >= 3  # at least 3 cohort bands
    for band in bands:
        assert "cohort" in band
        assert "expected_narrow_rate_min" in band
        assert "expected_narrow_rate_max" in band
        assert "source" in band
