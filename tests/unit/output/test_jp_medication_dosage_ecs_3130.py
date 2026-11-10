"""Issue #3130: JP MedicationRequest dosage conforms to JP_MedicationDosage_eCS.

JP-CLINS 1.13.0 ``StructureDefinition-jp-medicationdosage-eCS.json``:
``timing.code.text`` min 1; the uncoded usage slice fixes the display to
``ダミー用法コード``; ``timing.repeat.bounds[x]`` only as a Duration;
``doseAndRate.rate[x]`` only as a Ratio (``JP_MedicationRatio_DosePerDay``:
denominator 1 日). The effective status of a pinned-``completed`` request is
carried in ``note`` (a ``urn:`` extension has no definition the validator can
resolve).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.post_process.populate import (
    _populate_condition_ai_mr_ecs_fields,
    _populate_jp_medication_dosage_ecs_fields,
)

pytestmark = pytest.mark.unit

_UNCODED = "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_MedicationUsage_Uncoded_CS"


def _mr(dosage: dict) -> dict:
    return {
        "resourceType": "MedicationRequest",
        "authoredOn": "2026-03-01T09:00:00+09:00",
        "medicationCodeableConcept": {"text": "ノルアドレナリン"},
        "dosageInstruction": [dosage],
    }


def test_timing_code_text_is_always_set() -> None:
    r = _mr({"text": "0.1ug/kg/分 点滴静注", "timing": {"repeat": {"frequency": 1, "period": 7, "periodUnit": "d"}}})
    _populate_jp_medication_dosage_ecs_fields(r)
    assert r["dosageInstruction"][0]["timing"]["code"]["text"]


def test_uncoded_usage_has_the_fixed_display_and_the_usage_in_text() -> None:
    r = _mr({"text": "50mg 静注", "timing": {"repeat": {"frequency": 24, "period": 1, "periodUnit": "d"}}})
    _populate_jp_medication_dosage_ecs_fields(r)
    code = r["dosageInstruction"][0]["timing"]["code"]
    [coding] = [c for c in code["coding"] if c["system"] == _UNCODED]
    assert coding == {"system": _UNCODED, "code": "0X0XXXXXXXXX0000", "display": "ダミー用法コード"}
    assert code["text"] == "1日24回"


def test_bounds_period_moves_to_the_period_of_use() -> None:
    r = _mr(
        {
            "text": "5mg 経口 1日1回",
            "timing": {
                "repeat": {
                    "frequency": 1,
                    "period": 1,
                    "periodUnit": "d",
                    "boundsPeriod": {"start": "2026-03-01T09:00:00+09:00", "end": "2026-03-10T10:00:00+09:00"},
                }
            },
        }
    )
    _populate_jp_medication_dosage_ecs_fields(r)
    d = r["dosageInstruction"][0]
    repeat = d["timing"]["repeat"]
    assert "boundsPeriod" not in repeat
    assert repeat["boundsDuration"]["code"] == "d"
    [period] = [e["valuePeriod"] for e in d["extension"] if e["url"].endswith("JP_MedicationDosage_PeriodOfUse")]
    assert period == {"start": "2026-03-01T09:00:00+09:00", "end": "2026-03-10T10:00:00+09:00"}


@pytest.mark.parametrize(
    ("rate", "numerator"),
    [
        ({"value": 125, "unit": "mL/h", "system": "http://unitsofmeasure.org", "code": "mL/h"}, (3000, "mL")),
        (
            {"value": 0.1, "unit": "ug/kg/min", "system": "http://unitsofmeasure.org", "code": "ug/kg/min"},
            (144, "ug/kg"),
        ),
    ],
)
def test_rate_is_a_ratio_per_day(rate: dict, numerator: tuple) -> None:
    r = _mr({"text": "持続", "doseAndRate": [{"rateQuantity": rate}]})
    _populate_jp_medication_dosage_ecs_fields(r)
    dar = r["dosageInstruction"][0]["doseAndRate"][0]
    assert "rateQuantity" not in dar
    ratio = dar["rateRatio"]
    assert (ratio["numerator"]["value"], ratio["numerator"]["code"]) == numerator
    assert ratio["denominator"] == {"value": 1, "unit": "日", "system": "http://unitsofmeasure.org", "code": "d"}


def test_effective_status_is_a_note_not_an_extension() -> None:
    r = _mr({"text": "5mg 経口 1日1回"})
    r["status"] = "active"
    _populate_condition_ai_mr_ecs_fields(r, "JP")
    assert r["status"] == "completed"
    assert not any("effective-status" in e.get("url", "") for e in r.get("extension", []))
    assert r["note"]


def test_us_request_keeps_its_status_and_shape() -> None:
    r = _mr({"text": "5 mg PO daily"})
    r["status"] = "active"
    _populate_condition_ai_mr_ecs_fields(r, "US")
    assert r["status"] == "active" and "note" not in r


@pytest.mark.parametrize(
    ("repeat", "text", "usage"),
    [
        ({"frequency": 1, "period": 1, "periodUnit": "wk"}, "35mg", "週1回"),
        ({"frequency": 1, "period": 1, "periodUnit": "mo"}, "3.75mg", "月1回"),
        ({"count": 1}, "50 mcg", "1回"),
        ({}, "35mg", "用法未指定"),
    ],
)
def test_timing_text_states_a_usage_not_a_dose(repeat: dict, text: str, usage: str) -> None:
    r = _mr({"text": text, "timing": {"repeat": repeat}})
    _populate_jp_medication_dosage_ecs_fields(r)
    assert r["dosageInstruction"][0]["timing"]["code"]["text"] == usage
