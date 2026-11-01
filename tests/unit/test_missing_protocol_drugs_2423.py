"""Protocol drugs that were missing from the catalog are catalogued with
verified codes, and their protocol entries use drug_id (Issue #2423)."""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import get_drug

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("drug_id", "rxnorm", "yj"),
    [
        ("andexanet_alfa", "2045114", None),
        ("imipenem_cilastatin", "34482", "6139501D2105"),
        ("terlipressin", "57048", None),
        ("rebamipide", None, "2329021F1102"),
        ("oxycodone_acetaminophen", "214183", None),
        ("dextrose_5_sodium_chloride_045", "1795250", None),
    ],
)
def test_catalogued(drug_id: str, rxnorm: str | None, yj: str | None) -> None:
    rec = get_drug(drug_id)
    assert rec is not None
    assert rec.codes.get("rxnorm") == rxnorm
    assert rec.codes.get("yj") == yj
    assert rec.names["en"] and rec.names["ja"]
