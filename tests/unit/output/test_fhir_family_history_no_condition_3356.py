"""Issue #3356: a relative with no sampled condition states "no significant family history"."""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.modules.output.fhir_r4.demographics.family_history import _bb_family_history
from clinosim.modules.output.fhir_r4.lib.context import BundleContext

pytestmark = pytest.mark.unit


def _build(country: str, codes: list[str]) -> dict[str, Any]:
    ctx = BundleContext(
        record={"family_history": [{"relationship": "MTH", "deceased": False, "condition_codes": codes}]},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pt-1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="",
        patient_sex="",
    )
    result = _bb_family_history(ctx)
    assert len(result) == 1
    return result[0]


def test_us_empty_condition_codes_state_no_significant_history() -> None:
    fmh = _build("US", [])
    (cond,) = fmh["condition"]
    coding = cond["code"]["coding"][0]
    assert coding == {
        "system": "http://snomed.info/sct",
        "code": "160266009",
        "display": "No significant family history",
    }
    assert "text" not in cond["code"]
    assert "dataAbsentReason" not in fmh


def test_jp_empty_condition_codes_dual_slot_japanese_text() -> None:
    fmh = _build("JP", [])
    (cond,) = fmh["condition"]
    assert cond["code"]["coding"][0]["code"] == "160266009"
    assert cond["code"]["coding"][0]["display"] == "No significant family history"
    assert cond["code"]["text"] == "特記家族歴なし"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_relative_with_conditions_is_unchanged(country: str) -> None:
    fmh = _build(country, ["I25"])
    (cond,) = fmh["condition"]
    assert cond["code"]["coding"][0]["code"] != "160266009"
    assert "onsetString" in cond
