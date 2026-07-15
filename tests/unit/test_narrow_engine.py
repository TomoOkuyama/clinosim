"""PR3b-3: select_narrow_target + narrow_outcome + narrow_duration_days tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP
from clinosim.modules.antibiotic.engine import (
    NarrowOutcome,
    narrow_duration_days,
    narrow_outcome,
    select_narrow_target,
)
from clinosim.types.antibiotic import AntibioticRegimen
from clinosim.types.microbiology import SusceptibilityResult


def _sr(drug_key: str, interp: str) -> SusceptibilityResult:
    return SusceptibilityResult(
        antibiotic_loinc=ANTIBIOTIC_LOINC_LOOKUP[drug_key],
        interpretation=interp,
    )


def _ar(drug_key: str, start_offset_days: int = 0) -> AntibioticRegimen:
    base = datetime(2026, 1, 1)
    return AntibioticRegimen(
        regimen_id=f"abx-test-{drug_key}",
        hai_event_id="h-test",
        encounter_id="enc-test",
        drug_key=drug_key,
        dose="1g",
        route="IV",
        frequency="q12h",
        start_datetime=base.replace(day=1 + start_offset_days),
        duration_days=14,
        intent="empirical",
    )


# --- select_narrow_target ---


@pytest.mark.unit
def test_select_narrow_target_first_s_wins() -> None:
    """Ladder walk picks the first S even if later entries are also S."""
    susc = [_sr("cefazolin", "S"), _sr("vancomycin", "S")]
    ladder = ["cefazolin", "vancomycin"]
    assert select_narrow_target(susc, ladder) == "cefazolin"


@pytest.mark.unit
def test_select_narrow_target_skips_r_and_i() -> None:
    """R and I entries skip to the next ladder candidate."""
    susc = [
        _sr("cefazolin", "R"),
        _sr("ceftriaxone", "I"),
        _sr("vancomycin", "S"),
    ]
    ladder = ["cefazolin", "ceftriaxone", "vancomycin"]
    assert select_narrow_target(susc, ladder) == "vancomycin"


@pytest.mark.unit
def test_select_narrow_target_returns_none_on_empty_ladder() -> None:
    susc = [_sr("cefazolin", "S")]
    assert select_narrow_target(susc, []) is None


@pytest.mark.unit
def test_select_narrow_target_returns_none_on_all_non_s() -> None:
    susc = [_sr("cefazolin", "R"), _sr("vancomycin", "I")]
    ladder = ["cefazolin", "vancomycin"]
    assert select_narrow_target(susc, ladder) is None


@pytest.mark.unit
def test_select_narrow_target_returns_none_on_empty_susc() -> None:
    ladder = ["cefazolin", "vancomycin"]
    assert select_narrow_target([], ladder) is None


@pytest.mark.unit
def test_select_narrow_target_skips_drug_not_in_susc() -> None:
    """Ladder entries with no matching susceptibility result are silently
    skipped (treated like non-S)."""
    susc = [_sr("vancomycin", "S")]
    ladder = ["cefazolin", "vancomycin"]  # cefazolin absent in susc
    assert select_narrow_target(susc, ladder) == "vancomycin"


# --- narrow_outcome ---


@pytest.mark.unit
def test_narrow_outcome_no_change_when_target_is_none() -> None:
    """ladder all-non-S returns None → NO_CHANGE."""
    assert narrow_outcome(None, [_ar("vancomycin"), _ar("piperacillin_tazobactam")]) == NarrowOutcome.NO_CHANGE


@pytest.mark.unit
def test_narrow_outcome_no_change_when_single_empirical_equals_target() -> None:
    """Case (iii): CAUTI ceftriaxone × empirical ceftriaxone → NO_CHANGE."""
    assert narrow_outcome("ceftriaxone", [_ar("ceftriaxone")]) == NarrowOutcome.NO_CHANGE


@pytest.mark.unit
def test_narrow_outcome_elimination_when_target_in_multi_empirical() -> None:
    """Case (ii): CLABSI MRSA — vancomycin S in empirical {vanc + pip-tazo}
    → ELIMINATION (keep vanc, discontinue pip-tazo)."""
    assert (
        narrow_outcome("vancomycin", [_ar("vancomycin"), _ar("piperacillin_tazobactam")]) == NarrowOutcome.ELIMINATION
    )


@pytest.mark.unit
def test_narrow_outcome_switch_when_target_not_in_empirical() -> None:
    """Case (i): CLABSI MSSA — cefazolin S, empirical {vanc + pip-tazo}
    → SWITCH (discontinue all, add new narrow regimen)."""
    assert narrow_outcome("cefazolin", [_ar("vancomycin"), _ar("piperacillin_tazobactam")]) == NarrowOutcome.SWITCH


# --- narrow_duration_days ---


@pytest.mark.unit
def test_narrow_duration_days_subtracts_elapsed() -> None:
    """narrow duration = total - (reported - start).days."""
    start = datetime(2026, 1, 1)
    reported = datetime(2026, 1, 3)  # 2 days later
    assert narrow_duration_days(start, reported, total_course=14) == 12


@pytest.mark.unit
def test_narrow_duration_days_returns_zero_when_reported_past_course() -> None:
    """Defensive clamp: never negative (clamps at 0)."""
    start = datetime(2026, 1, 1)
    reported = datetime(2026, 1, 20)  # 19 days, > 14 total
    assert narrow_duration_days(start, reported, total_course=14) == 0
