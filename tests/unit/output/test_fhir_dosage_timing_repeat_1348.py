"""Issue #1348: MedicationRequest.dosageInstruction.timing.repeat coverage.

Regression tests for the expanded _FREQ_LABEL_TIMING table introduced to
close the "no BID / no weekly / no monthly / no per-cycle" gap on emitted
MedicationRequest resources.

Cohort audit against a p=10k S=356 US build before the fix:
    - Salbutamol   4787/4787   (100.0 %)  → PRN, correctly asNeededBoolean=true
    - Alendronate  1281/1283   (99.8 %)   → `weekly` label unknown to derivation
    - Mirtazapine   143/143    (100.0 %)  → `nightly` label unknown to derivation
    - Oxaliplatin   123/351    (35.0 %)   → `q3weeks` chemo cycle unknown
The catalog additions here close each gap; PRN remains asNeededBoolean.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.lib.common import build_dosage_instruction


@pytest.mark.parametrize(
    "freq,expected_freq,expected_period,expected_unit",
    [
        # Once-daily variants (already covered pre-fix; regression guard)
        ("qd", 1, 1, "d"),
        ("daily", 1, 1, "d"),
        ("q24h", 1, 1, "d"),
        ("once daily", 1, 1, "d"),
        ("qhs", 1, 1, "d"),
        ("bedtime", 1, 1, "d"),
        # New once-daily aliases
        ("nightly", 1, 1, "d"),
        ("qam", 1, 1, "d"),
        ("qpm", 1, 1, "d"),
        # Multiple times per day (regression guard)
        ("bid", 2, 1, "d"),
        ("BID", 2, 1, "d"),  # uppercase folds
        ("q12h", 2, 1, "d"),
        ("tid", 3, 1, "d"),
        ("q8h", 3, 1, "d"),
        ("qid", 4, 1, "d"),
        ("q6h", 4, 1, "d"),
        ("q4h", 6, 1, "d"),
        ("q1h", 24, 1, "d"),
        # NEW: multi-day cadence
        ("every_other_day", 1, 2, "d"),
        ("qod", 1, 2, "d"),
        ("every_3_days", 1, 3, "d"),
        # NEW: weekly cadence
        ("weekly", 1, 1, "wk"),
        ("1x/week", 1, 1, "wk"),
        ("qweek", 1, 1, "wk"),
        ("once weekly", 1, 1, "wk"),
        # NEW: monthly cadence
        ("monthly", 1, 1, "mo"),
        ("qmonth", 1, 1, "mo"),
        # NEW: chemo per-cycle cadence
        ("q3weeks", 1, 3, "wk"),
        ("q3wks", 1, 3, "wk"),
        ("every 3 weeks", 1, 3, "wk"),
        ("q4wks", 1, 4, "wk"),
    ],
)
def test_freq_label_emits_timing_repeat(
    freq: str, expected_freq: int, expected_period: int, expected_unit: str
) -> None:
    order = {"dose_quantity": 10, "dose_unit": "mg", "route": "PO", "frequency": freq}
    dosage = build_dosage_instruction(order)
    assert dosage is not None
    repeat = dosage.get("timing", {}).get("repeat", {})
    assert repeat.get("frequency") == expected_freq, dosage
    assert repeat.get("period") == expected_period, dosage
    assert repeat.get("periodUnit") == expected_unit, dosage


class TestPRNSemantics:
    """PRN drugs must set asNeededBoolean=true; ``<cadence> PRN`` combos
    must set BOTH the cadence in timing.repeat AND asNeededBoolean=true."""

    def test_prn_alone_sets_asneeded_no_timing(self) -> None:
        order = {"dose_quantity": 100, "dose_unit": "mcg", "route": "INH", "frequency": "prn"}
        dosage = build_dosage_instruction(order)
        assert dosage is not None
        assert dosage.get("asNeededBoolean") is True
        # No fixed cadence.
        assert "timing" not in dosage or "repeat" not in (dosage.get("timing") or {})

    def test_q6h_prn_sets_both(self) -> None:
        order = {"dose_quantity": 500, "dose_unit": "mg", "route": "PO", "frequency": "q6h PRN"}
        dosage = build_dosage_instruction(order)
        assert dosage is not None
        assert dosage.get("asNeededBoolean") is True
        repeat = dosage["timing"]["repeat"]
        assert repeat["frequency"] == 4
        assert repeat["periodUnit"] == "d"

    def test_tid_prn_sets_both(self) -> None:
        order = {"dose_quantity": 500, "dose_unit": "mg", "route": "PO", "frequency": "tid PRN"}
        dosage = build_dosage_instruction(order)
        assert dosage is not None
        assert dosage.get("asNeededBoolean") is True
        repeat = dosage["timing"]["repeat"]
        assert repeat["frequency"] == 3
        assert repeat["periodUnit"] == "d"

    def test_prn_case_insensitive(self) -> None:
        order = {"dose_quantity": 500, "dose_unit": "mg", "route": "PO", "frequency": "Q6H PRN"}
        dosage = build_dosage_instruction(order)
        assert dosage is not None
        assert dosage.get("asNeededBoolean") is True
        repeat = dosage["timing"]["repeat"]
        assert repeat["frequency"] == 4


class TestUnknownFrequency:
    """Unknown frequency labels leave the emit path unchanged (no timing.repeat).

    The prior "text-only" branch is intentionally kept for author-freeform
    labels like ``q6h_first_24h_then_daily`` where FHIR repeat can't express
    the true cadence — a bare `text` summary is more honest than a wrong
    numeric repeat.
    """

    def test_unknown_label_no_timing(self) -> None:
        order = {
            "dose_quantity": 100,
            "dose_unit": "mg",
            "route": "PO",
            "frequency": "q6h_first_24h_then_daily",
        }
        dosage = build_dosage_instruction(order)
        assert dosage is not None
        assert "timing" not in dosage or "repeat" not in (dosage.get("timing") or {})
        # The freeform label still lands in the text summary for provenance.
        assert "q6h_first_24h_then_daily" in dosage.get("text", "")
