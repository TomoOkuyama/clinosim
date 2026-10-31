"""Thiazide diuretics and lithium are classified so their interactions are checked (Issue #2253)."""

from __future__ import annotations

import pytest

from clinosim.modules.drug_safety.classifier import resolve_classes
from clinosim.modules.drug_safety.engine import check_pair

pytestmark = pytest.mark.unit


def test_hydrochlorothiazide_is_a_thiazide_diuretic() -> None:
    assert "diuretic.thiazide" in resolve_classes("Hydrochlorothiazide")


def test_lithium_has_a_class() -> None:
    assert "lithium" in resolve_classes("Lithium carbonate")


@pytest.mark.parametrize("other", ["Hydrochlorothiazide", "Furosemide", "Lisinopril", "Losartan", "Ibuprofen"])
def test_lithium_raising_drugs_are_flagged_for_monitoring(other: str) -> None:
    # FDA lithium label section 7: diuretics, renin-angiotensin system
    # antagonists and NSAIDs raise serum lithium; monitor and adjust the dose.
    verdict = check_pair("Lithium carbonate", other)
    assert verdict.severity == "moderate", (other, verdict)
    assert check_pair(other, "Lithium carbonate").severity == "moderate"
