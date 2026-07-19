"""Unit tests for `_populate_jp_medication_dosage_ecs_fields` walker.

JP-CLINS 1.12.0 `JP_MedicationDosage_eCS` layers three requirements on top
of the base `Dosage` type that clinosim's builder does not emit:

- `Dosage.extension:periodOfUse` (min=1) — a `Period` with `start` marking
  the day the dose becomes effective.
- `Dosage.timing.code.coding` (min=1) satisfying R5020 — exactly one of
  MHLW ePrescription CS OR the JP-CLINS uncoded dummy code.
- `Dosage.timing.code.text` (min=1).

Feedback fix (2026-07-16, PR-I).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4_adapter import (
    _JP_CLINS_MEDICATION_USAGE_UNCODED_CODE,
    _JP_CLINS_MEDICATION_USAGE_UNCODED_CS,
    _JP_CLINS_MEDICATION_USAGE_UNCODED_DISPLAY,
    _JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL,
    _JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS,
    _JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS,
    _JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_CODE,
    _JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_DISPLAY,
    _UCUM_DAY_CODE,
    _UCUM_DAY_UNIT_JA,
    _UCUM_SYSTEM_URI,
    _populate_jp_medication_dosage_ecs_fields,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# periodOfUse extension
# ---------------------------------------------------------------------------


def test_period_of_use_extension_added_from_authored_on():
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "authoredOn": "2025-11-25T14:24:00+09:00",
        "dosageInstruction": [{"text": "1日3回 毎食後"}],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    exts = r["dosageInstruction"][0]["extension"]
    ext = next(e for e in exts if e["url"] == _JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL)
    assert ext["valuePeriod"]["start"] == "2025-11-25"


def test_period_of_use_extension_falls_back_to_recorded():
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "recorded": "2025-01-15T09:00:00+09:00",
        "dosageInstruction": [{"text": "1日1回"}],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    ext = r["dosageInstruction"][0]["extension"][0]
    assert ext["valuePeriod"]["start"] == "2025-01-15"


def test_period_of_use_not_added_when_no_datetime_source():
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "dosageInstruction": [{"text": "1日1回"}],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    exts = r["dosageInstruction"][0].get("extension", [])
    assert not any(e.get("url") == _JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL for e in exts)


def test_period_of_use_idempotent_when_already_set():
    pre_ext = {
        "url": _JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL,
        "valuePeriod": {"start": "2020-01-01"},
    }
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "authoredOn": "2025-11-25T14:24:00+09:00",
        "dosageInstruction": [{"text": "x", "extension": [pre_ext]}],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    exts = r["dosageInstruction"][0]["extension"]
    # Only one periodOfUse (pre-existing) — walker did not add a duplicate.
    periodofuse = [e for e in exts if e["url"] == _JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL]
    assert len(periodofuse) == 1
    assert periodofuse[0]["valuePeriod"]["start"] == "2020-01-01"


# ---------------------------------------------------------------------------
# timing.code (R5020: dummy uncoded XOR MHLW ePrescription)
# ---------------------------------------------------------------------------


def test_timing_code_dummy_uncoded_added_when_missing():
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "authoredOn": "2025-11-25T14:24:00+09:00",
        "dosageInstruction": [{"text": "1日3回 毎食後"}],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    code = r["dosageInstruction"][0]["timing"]["code"]
    assert len(code["coding"]) == 1
    coding = code["coding"][0]
    assert coding == {
        "system": _JP_CLINS_MEDICATION_USAGE_UNCODED_CS,
        "code": _JP_CLINS_MEDICATION_USAGE_UNCODED_CODE,
        "display": _JP_CLINS_MEDICATION_USAGE_UNCODED_DISPLAY,
    }


def test_timing_code_text_falls_back_to_dosage_text():
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "dosageInstruction": [{"text": "1日3回 毎食後"}],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    assert r["dosageInstruction"][0]["timing"]["code"]["text"] == "1日3回 毎食後"


def test_timing_code_text_falls_back_to_dummy_display_when_no_dosage_text():
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "dosageInstruction": [{}],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    assert r["dosageInstruction"][0]["timing"]["code"]["text"] == _JP_CLINS_MEDICATION_USAGE_UNCODED_DISPLAY


def test_timing_code_preserves_pre_existing_mhlw_coding():
    """If a builder already emits an MHLW ePrescription coding, R5020 is
    satisfied and the walker must NOT add a duplicate dummy coding
    (would violate the XOR constraint)."""
    pre_coding = {
        "system": _JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS,
        "code": "some-mhlw-code",
        "display": "MHLW display",
    }
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "dosageInstruction": [{"text": "x", "timing": {"code": {"coding": [pre_coding], "text": "pre"}}}],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    codings = r["dosageInstruction"][0]["timing"]["code"]["coding"]
    assert len(codings) == 1
    assert codings[0] == pre_coding


def test_timing_code_preserves_pre_existing_dummy_coding():
    """Same idempotency guarantee for the dummy CS."""
    pre_coding = {
        "system": _JP_CLINS_MEDICATION_USAGE_UNCODED_CS,
        "code": _JP_CLINS_MEDICATION_USAGE_UNCODED_CODE,
        "display": _JP_CLINS_MEDICATION_USAGE_UNCODED_DISPLAY,
    }
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "dosageInstruction": [{"text": "x", "timing": {"code": {"coding": [pre_coding], "text": "pre"}}}],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    codings = r["dosageInstruction"][0]["timing"]["code"]["coding"]
    assert len(codings) == 1  # no duplication


# ---------------------------------------------------------------------------
# Multiple dosageInstruction[] + non-MR safety
# ---------------------------------------------------------------------------


def test_all_dosage_instructions_receive_fields():
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "authoredOn": "2025-11-25T14:24:00+09:00",
        "dosageInstruction": [
            {"text": "AM"},
            {"text": "PM"},
        ],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    for i in range(2):
        di = r["dosageInstruction"][i]
        assert any(e["url"] == _JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL for e in di["extension"])
        codings = di["timing"]["code"]["coding"]
        assert any(c["system"] == _JP_CLINS_MEDICATION_USAGE_UNCODED_CS for c in codings)
    # timing.code.text carries the per-dose text
    assert r["dosageInstruction"][0]["timing"]["code"]["text"] == "AM"
    assert r["dosageInstruction"][1]["timing"]["code"]["text"] == "PM"


def test_ignores_non_medication_request_resources():
    r = {"resourceType": "Observation", "id": "obs1", "dosageInstruction": [{"text": "x"}]}
    _populate_jp_medication_dosage_ecs_fields(r)
    # dosageInstruction untouched
    assert r["dosageInstruction"][0] == {"text": "x"}


def test_no_op_when_no_dosage_instruction():
    r = {"resourceType": "MedicationRequest", "id": "mr1"}
    _populate_jp_medication_dosage_ecs_fields(r)
    assert "dosageInstruction" not in r


def test_idempotent_double_pass():
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "authoredOn": "2025-11-25T14:24:00+09:00",
        "dosageInstruction": [{"text": "1日3回"}],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    after_first = r["dosageInstruction"][0]
    _populate_jp_medication_dosage_ecs_fields(r)
    after_second = r["dosageInstruction"][0]
    assert after_first == after_second
    assert len(after_second["extension"]) == 1
    assert len(after_second["timing"]["code"]["coding"]) == 1


# ---------------------------------------------------------------------------
# Session 58 Chain #2: doseAndRate.type (min=1) + periodUnit → boundsDuration
# ---------------------------------------------------------------------------


def test_dose_and_rate_type_inserted_when_missing():
    """`Dosage.doseAndRate.type` min=1 (eCS). Walker adds MHLW MedicationIngredient
    StrengthType `1 / 製剤量` coding per JP-CLINS example fixture."""
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "authoredOn": "2025-11-25T14:24:00+09:00",
        "dosageInstruction": [
            {
                "text": "1日3回",
                "doseAndRate": [{"doseQuantity": {"value": 2, "unit": "錠"}}],
            }
        ],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    dr = r["dosageInstruction"][0]["doseAndRate"][0]
    assert dr["type"]["coding"][0] == {
        "system": _JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS,
        "code": _JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_CODE,
        "display": _JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_DISPLAY,
    }


def test_dose_and_rate_type_not_overwritten_when_present():
    """Walker skips when a builder already emitted a `doseAndRate[i].type`."""
    pre = {"coding": [{"system": "http://example.org/other", "code": "X", "display": "X"}]}
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "authoredOn": "2025-11-25T14:24:00+09:00",
        "dosageInstruction": [{"text": "1日3回", "doseAndRate": [{"type": pre}]}],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    assert r["dosageInstruction"][0]["doseAndRate"][0]["type"] == pre


def test_period_unit_d_stripped_and_bounds_duration_added():
    """#307 session 60:walker は `timing.repeat.periodUnit='d'` +
    `period` を pop し `boundsDuration` を代わりに emit する(session 58
    Chain #2 の元の狙いに復帰、pragmatic middle path)。

    - session 58 Chain #2:boundsDuration only 化(UnitsOfTime binding 回避)
    - session 59 #281:JP-CLINS example fixture 準拠で `periodUnit` pop 撤回
    - v6 (session 60):HAPI validator が `periodUnit=code` の binding 検証で
      system URI を決定できず 3,532 件 UnitsOfTime error(v5 では 0 件)
    - #307:JP-CLINS example ≠ spec required。boundsDuration + frequency
      で per-day cadence を保持できるので pop 復活で spec-valid かつ
      HAPI validator green。tim-2 non-fire(period 消えるので pair 不成立)。
    """
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "authoredOn": "2025-11-25T14:24:00+09:00",
        "dosageInstruction": [
            {
                "text": "1日1回",
                "timing": {"repeat": {"frequency": 1, "period": 1, "periodUnit": "d"}},
            }
        ],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    repeat = r["dosageInstruction"][0]["timing"]["repeat"]
    # #307 session 60: periodUnit + period stripped after boundsDuration
    # is populated. HAPI validator UnitsOfTime binding error 回避 + tim-2
    # non-fire。
    assert "periodUnit" not in repeat
    assert "period" not in repeat
    # boundsDuration 追加(session 58 Chain #2 intent restored)。
    assert repeat["boundsDuration"] == {
        "value": 1,
        "unit": _UCUM_DAY_UNIT_JA,
        "system": _UCUM_SYSTEM_URI,
        "code": _UCUM_DAY_CODE,
    }
    # frequency は保持(per-day cadence 意味を担う)。
    assert repeat["frequency"] == 1


def test_period_unit_non_day_left_untouched():
    """Only `periodUnit=='d'` triggers the rewrite; `h` / `wk` etc. bypass
    (their UCUM resolution is a separate concern out of Chain #2's scope)."""
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "authoredOn": "2025-11-25T14:24:00+09:00",
        "dosageInstruction": [
            {"text": "8時間ごと", "timing": {"repeat": {"frequency": 1, "period": 8, "periodUnit": "h"}}}
        ],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    repeat = r["dosageInstruction"][0]["timing"]["repeat"]
    assert repeat["periodUnit"] == "h"
    assert "boundsDuration" not in repeat


def test_bounds_duration_not_overwritten_when_builder_supplied():
    """Walker preserves builder-supplied `boundsDuration`."""
    pre = {"value": 7, "unit": "日", "system": _UCUM_SYSTEM_URI, "code": _UCUM_DAY_CODE}
    r = {
        "resourceType": "MedicationRequest",
        "id": "mr1",
        "authoredOn": "2025-11-25T14:24:00+09:00",
        "dosageInstruction": [
            {
                "text": "7日間",
                "timing": {
                    "repeat": {
                        "frequency": 1,
                        "period": 1,
                        "periodUnit": "d",
                        "boundsDuration": pre,
                    }
                },
            }
        ],
    }
    _populate_jp_medication_dosage_ecs_fields(r)
    repeat = r["dosageInstruction"][0]["timing"]["repeat"]
    assert repeat["boundsDuration"] == pre
    # #307 session 60: builder が boundsDuration を pre-populate 済でも
    # walker は同じく periodUnit + period を pop する(HAPI validator
    # UnitsOfTime binding error 回避のため、条件式は periodUnit == "d"
    # gate なので pre-populated boundsDuration も安全に pop 経路に乗る)。
    assert "periodUnit" not in repeat
    assert "period" not in repeat
