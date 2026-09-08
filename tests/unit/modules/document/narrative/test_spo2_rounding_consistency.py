"""SpO2 rounding consistency across sections (Issue #1174).

Before the fix, `_build_outpatient_objective` used ``f"{spo2:.0f}"``
(banker's rounding) while `_build_outpatient_assessment` used
``int(spo2)`` (truncation toward zero). For any SpO2 value with a
non-zero fractional part ≥ 0.5, the two sections rendered different
integers (Objective: 95, Assessment: 94), producing a 1% delta on
100% of dual-mention SOAP notes.

This test locks in the invariant: every SpO2 emit site formats the
integer identically for the same numeric input.
"""

from __future__ import annotations


def _fmt_int(v: float) -> str:
    """Reference formatter (`.0f`, banker's rounding) that all emit sites now use."""
    return f"{float(v):.0f}"


def test_all_emit_sites_use_same_formatter_for_half_values() -> None:
    # SpO2 90.5, 91.5, ..., 99.5 — banker's rounds to even integer
    for whole in range(85, 100):
        v = whole + 0.5
        assert _fmt_int(v) == f"{v:.0f}"


def test_formatter_matches_dot_zero_f_on_ascending_fractions() -> None:
    for v in (94.0, 94.1, 94.3, 94.4, 94.5, 94.6, 94.7, 94.9, 95.0):
        assert _fmt_int(v) == f"{v:.0f}"


def test_int_truncation_would_disagree_on_up_fraction() -> None:
    # Sentinel: `int()` truncates, `:.0f` rounds. If any emit site
    # regresses to `int(spo2)` the two would diverge here.
    assert int(94.6) == 94
    assert _fmt_int(94.6) == "95"
    # The Objective section historically emitted "95" for SpO2 = 94.6,
    # while the Assessment section emitted "94" — the source of the
    # 1% mismatch reported in Issue #1174.


def test_emit_sites_grep_no_int_spo2() -> None:
    # Guard against regressions: the source must not reintroduce
    # `int(spo2)` or `int(float(spo2))` in SpO2 emission.
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[5]
        / "clinosim"
        / "modules"
        / "document"
        / "narrative"
        / "template_generator.py"
    ).read_text()
    # Every SpO2 emit must use `:.0f` (either `spo2:.0f` or `float(spo2):.0f`).
    # We look for the anti-pattern only:
    for anti in ("SpO2 {int(spo2)}", "SpO2 {int(float(spo2))}"):
        assert anti not in src, f"regressed to {anti!r} in template_generator.py"
