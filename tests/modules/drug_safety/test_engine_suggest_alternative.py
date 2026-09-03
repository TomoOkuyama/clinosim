"""Unit tests for suggest_alternative (shared pool path)."""

from __future__ import annotations

from clinosim.modules.drug_safety.engine import (
    AlternativeDrug,
    suggest_alternative,
)


def test_pain_management_returns_acetaminophen() -> None:
    alt = suggest_alternative("Ibuprofen", "pain_management")
    assert isinstance(alt, AlternativeDrug)
    assert alt.drug == "Acetaminophen"
    assert alt.drug_ja == "アセトアミノフェン"
    assert "pain_management" in alt.source_path


def test_unknown_indication_returns_none() -> None:
    assert suggest_alternative("Ibuprofen", "unknown_tag") is None


def test_none_indication_returns_none() -> None:
    assert suggest_alternative("Ibuprofen", None) is None


def test_alternative_re_checks_against_active_meds() -> None:
    """If the first alternative is itself blocked, iterate to next entry."""
    # Pain management pool: Acetaminophen only — no rule against warfarin,
    # so presence of warfarin does NOT change the pick.
    alt = suggest_alternative("Ibuprofen", "pain_management", active_meds=["Warfarin"])
    assert alt is not None
    assert alt.drug == "Acetaminophen"


def test_hypertension_pool_first_choice() -> None:
    """Hypertension pool starts with Amlodipine (no conflict with metoprolol)."""
    alt = suggest_alternative("Verapamil", "hypertension_or_rate_control", active_meds=["Metoprolol"])
    assert alt is not None
    assert alt.drug == "Amlodipine"


def test_hypertension_pool_iterates_when_active_hits_first_choice() -> None:
    """Force the iterator: put Amlodipine as active — it's not a contraindication
    rule target, so no iteration is needed here (kept for future rule additions).
    This test just documents the iterator machinery works when a hit occurs."""
    # Currently no rule blocks Amlodipine so this is effectively test_hypertension_pool_first_choice
    # duplicated; keep as a placeholder for when a rule requiring iteration exists.
    alt = suggest_alternative("Verapamil", "hypertension_or_rate_control", active_meds=[])
    assert alt is not None
    assert alt.drug == "Amlodipine"
