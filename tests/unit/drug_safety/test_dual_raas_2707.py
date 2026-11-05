"""Issue #2707: an ACE inhibitor and an ARB are not given together."""

from __future__ import annotations

import pytest

from clinosim.modules import drug_safety

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("candidate", "active"), [("Enalapril", "Candesartan"), ("Losartan", "Lisinopril")])
def test_an_ace_inhibitor_and_an_arb_conflict(candidate: str, active: str) -> None:
    verdicts = drug_safety.check_candidate_against_active(candidate, [active])
    assert any(v.severity == "contraindicated" for v in verdicts)


def test_an_arb_alone_is_fine() -> None:
    assert not drug_safety.check_candidate_against_active("Candesartan", ["Amlodipine"])
