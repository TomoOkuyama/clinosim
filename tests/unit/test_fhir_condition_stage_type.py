"""Condition.stage.type must not carry a tumor-staging SNOMED code for non-cancer stages.

The staged chronic conditions (CKD G / NYHA / GOLD / asthma / CCS / hypertension Stage)
previously all emitted stage.type.coding = SNOMED 385356007 "Tumor stage finding" — a
cancer-staging code clinically wrong for every one of them. The stage value is carried
by stage.summary.text; the wrong type coding is removed.
"""

import pytest

from clinosim.modules.output._fhir_conditions import _build_conditions
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit


def _stage(code, stage_text):
    record = {
        "patient": {
            "chronic_conditions": [
                ChronicCondition(code=code, onset_date="2020-01-01", severity="moderate",
                                 stage=stage_text),
            ],
        },
        "encounters": [{"encounter_id": "E1", "encounter_type": "outpatient"}],
    }
    conditions = _build_conditions(record, "P1", "US")
    base = code.split(".")[0]
    return next(c for c in conditions if c["code"]["coding"][0]["code"].startswith(base))


@pytest.mark.parametrize("code,stage_text", [
    ("N18.3", "CKD G3a"),
    ("I50.9", "NYHA II"),
    ("J44.9", "GOLD 2"),
    ("I10", "Stage 2"),
    ("I25.10", "CCS I"),
])
def test_stage_summary_text_preserved(code, stage_text):
    c = _stage(code, stage_text)
    assert c["stage"][0]["summary"]["text"] == stage_text


@pytest.mark.parametrize("code,stage_text", [
    ("N18.3", "CKD G3a"),
    ("I50.9", "NYHA II"),
    ("I10", "Stage 2"),
])
def test_no_tumor_staging_code_on_noncancer_stage(code, stage_text):
    c = _stage(code, stage_text)
    stage_type = c["stage"][0].get("type", {})
    codes = [cd.get("code") for cd in stage_type.get("coding", [])]
    displays = [cd.get("display", "") for cd in stage_type.get("coding", [])]
    assert "385356007" not in codes, f"{code}: tumor-staging code 385356007 misapplied"
    assert not any("Tumor" in d for d in displays), f"{code}: 'Tumor stage finding' misapplied"
