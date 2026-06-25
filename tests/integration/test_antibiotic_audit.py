"""Integration: clinosim audit framework discovers + accepts the antibiotic module."""
import pytest

from clinosim.audit.registry import discover, get_registered


@pytest.mark.integration
def test_antibiotic_module_registered():
    discover()
    assert "antibiotic" in get_registered()


@pytest.mark.integration
def test_antibiotic_lift_firing_proof_passes_silent_no_op_axis():
    """The synthetic-record proof must report all expected actions fired.

    PR-90 教訓: this is the load-bearing gate that catches
    canonical-string mismatches, silent get-with-default lookups, and
    enricher-not-wired bugs.
    """
    discover()
    spec = get_registered()["antibiotic"]
    assert spec.lift_firing_proof is not None
    proof = spec.lift_firing_proof()
    assert proof["ext_antibiotic_count"] == 1
    assert proof["ext_antibiotic_drug"] == "Ceftriaxone"
    assert proof["ext_antibiotic_duration_days"] == 7
    assert proof["orders_medication_count"] == 1
    assert proof["mar_count"] == 7
    assert proof["mar_drug"] == "Ceftriaxone"
    # Closed-form: onset 2026-01-10 08:00 + 6 days = 2026-01-16 08:00
    from datetime import datetime
    assert proof["mar_first_dt"] == datetime(2026, 1, 10, 8)
    assert proof["mar_last_dt"] == datetime(2026, 1, 16, 8)
    # Verify expected matches actual (audit framework will do this)
    expected = proof["expected"]
    for k, v in expected.items():
        assert proof[k] == v, f"key {k}: actual={proof[k]!r} != expected={v!r}"
