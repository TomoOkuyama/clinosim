"""Issue #3675: the JP MHLW usage code follows the dosage's as-needed state."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.post_process.populate import _populate_jp_medication_dosage_ecs_fields

pytestmark = pytest.mark.unit

_MHLW = "MedicationUsage_ePrescription"
_UNCODED = "JP_CLINS_MedicationUsage_Uncoded_CS"
_PRN_FEVER = "発熱時　服用"


def _timing_code(drug: str, *, as_needed: bool, freq: int = 3) -> dict:
    dosage: dict = {
        "text": "500mg 経口",
        "route": {"text": "経口"},
        "timing": {"repeat": {"frequency": freq, "period": 1, "periodUnit": "d"}},
    }
    if as_needed:
        dosage["asNeededBoolean"] = True
    r = {
        "resourceType": "MedicationRequest",
        "authoredOn": "2026-03-01T09:00:00+09:00",
        "medicationCodeableConcept": {"text": drug},
        "dosageInstruction": [dosage],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    return r["dosageInstruction"][0]["timing"]["code"]


def _mhlw_displays(code: dict) -> list[str]:
    return [c["display"] for c in code["coding"] if _MHLW in c["system"]]


def test_scheduled_acetaminophen_never_gets_the_as_needed_usage() -> None:
    code = _timing_code("アセトアミノフェン", as_needed=False)
    assert _PRN_FEVER not in _mhlw_displays(code)
    assert code["text"] != _PRN_FEVER


def test_as_needed_acetaminophen_gets_the_fever_usage() -> None:
    code = _timing_code("アセトアミノフェン", as_needed=True)
    assert _mhlw_displays(code) == [_PRN_FEVER]
    assert code["text"] == _PRN_FEVER


def test_as_needed_drug_without_a_prn_code_is_uncoded_with_the_trigger_in_text() -> None:
    code = _timing_code("イブプロフェン", as_needed=True)
    assert _mhlw_displays(code) == []
    assert any(_UNCODED in c["system"] for c in code["coding"])
    assert code["text"] == "必要時（1日3回）"


def test_as_needed_without_cadence_states_as_needed() -> None:
    r = {
        "resourceType": "MedicationRequest",
        "authoredOn": "2026-03-01T09:00:00+09:00",
        "medicationCodeableConcept": {"text": "イブプロフェン"},
        "dosageInstruction": [{"text": "200mg", "asNeededBoolean": True}],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    assert r["dosageInstruction"][0]["timing"]["code"]["text"] == "必要時"


def test_scheduled_non_prn_drug_unchanged() -> None:
    code = _timing_code("ロキソプロフェン", as_needed=False)
    assert code["text"]
    assert "必要時" not in code["text"]
