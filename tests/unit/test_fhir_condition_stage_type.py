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


# --- stage.summary SNOMED coding for the verified staging systems (CKD, NYHA) ---

@pytest.mark.parametrize("code,stage_text,snomed,en", [
    ("N18.1", "CKD G1", "431855005", "Chronic kidney disease stage 1"),
    ("N18.2", "CKD G2", "431856006", "Chronic kidney disease stage 2"),
    ("N18.3", "CKD G3a", "700378005", "Chronic kidney disease stage 3A"),
    ("N18.3", "CKD G3b", "700379002", "Chronic kidney disease stage 3B"),
    ("N18.4", "CKD G4", "431857002", "Chronic kidney disease stage 4"),
    ("N18.5", "CKD G5", "433146000", "Chronic kidney disease stage 5"),
    ("I50.9", "NYHA I", "420300004", "New York Heart Association Classification - Class I"),
    ("I50.9", "NYHA II", "421704003", "New York Heart Association Classification - Class II"),
    ("I50.9", "NYHA III", "420913000", "New York Heart Association Classification - Class III"),
    ("I50.9", "NYHA IV", "422293003", "New York Heart Association Classification - Class IV"),
])
def test_ckd_nyha_stage_summary_snomed_coding_us(code, stage_text, snomed, en):
    c = _stage(code, stage_text)
    summary = c["stage"][0]["summary"]
    assert summary["text"] == stage_text  # raw stage text always preserved
    coding = summary["coding"][0]
    assert coding["system"] == "http://snomed.info/sct"
    assert coding["code"] == snomed
    assert coding["display"] == en


def test_stage_summary_coding_uses_jp_display():
    record = {
        "patient": {"chronic_conditions": [
            ChronicCondition(code="N18.3", onset_date="2020-01-01", severity="moderate",
                             stage="CKD G3a")]},
        "encounters": [{"encounter_id": "E1", "encounter_type": "outpatient"}],
    }
    c = next(x for x in _build_conditions(record, "P1", "JP")
             if x["code"]["coding"][0]["code"].startswith("N18"))
    coding = c["stage"][0]["summary"]["coding"][0]
    assert coding["code"] == "700378005"
    # JP output must localize display (SNOMED ja from snomed-ct.yaml).
    assert any(ord(ch) > 0x3000 for ch in coding["display"]), coding["display"]


@pytest.mark.parametrize("code,stage_text", [
    ("J44.9", "GOLD 2"),                  # COPD — no verified SNOMED staging code yet
    ("J45.909", "Moderate persistent"),   # asthma severity
    ("I10", "Stage 2"),                   # hypertension stage
    ("I25.10", "CCS I"),                  # CCS angina class
])
def test_unverified_staging_systems_remain_text_only(code, stage_text):
    c = _stage(code, stage_text)
    summary = c["stage"][0]["summary"]
    assert summary["text"] == stage_text
    assert "coding" not in summary, f"{stage_text}: emitted an unverified SNOMED coding"


def test_every_ckd_nyha_generated_stage_is_mapped():
    """Drift guard: every CKD/NYHA string _generate_stage can produce must be in
    the stage->SNOMED map, or the coding silently drops (the whitelist-drift bug
    class). Fails loud if activator adds a stage value without a code."""
    from clinosim.modules.output._fhir_conditions import _STAGE_SUMMARY_SNOMED

    ckd = [f"CKD {g}" for g in ("G1", "G2", "G3a", "G3b", "G4", "G5")]
    nyha = [f"NYHA {c}" for c in ("I", "II", "III", "IV")]
    for s in ckd + nyha:
        assert s in _STAGE_SUMMARY_SNOMED, f"unmapped generated stage: {s}"
