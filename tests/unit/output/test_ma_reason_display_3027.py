"""Issue #3027: a MedicationAdministration reason carries the ICD display and a
localized text, like the Condition it references."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import _build_ma_reason_block

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("country", "display", "text"),
    [
        ("US", "Chronic obstructive pulmonary disease with (acute) exacerbation", "COPD"),
        ("JP", "急性増悪を伴う慢性閉塞性肺疾患，詳細不明", "COPD（慢性閉塞性肺疾患）"),
    ],
)
def test_administration_reason_j44_1_has_the_icd_display(country: str, display: str, text: str) -> None:
    pair = _build_ma_reason_block("J44.1", None, "P1", "E1", country, "M")
    assert pair is not None
    [reason] = pair[1]
    [coding] = reason["coding"]
    assert coding["code"] == "J44.1"
    assert coding["display"] == display
    assert reason["text"] == text
