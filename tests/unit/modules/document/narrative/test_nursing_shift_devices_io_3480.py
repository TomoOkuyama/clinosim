"""Nursing shift note intake/output and device items (Issue #3480)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative.context import build_devices
from clinosim.modules.document.narrative.renderers.nursing_shift_note import render_nursing_shift_note

pytestmark = pytest.mark.unit

_ADM = "2026-08-31T09:54:00"
_ENC = {"encounter_id": "E1", "admission_datetime": _ADM, "primary_nurse_id": ""}


def _ctx(lang: str, day: int, shift: str = "day", **kw) -> SimpleNamespace:
    base = {
        "target_lang": lang,
        "locale": "jp" if lang == "ja" else "us",
        "authored_datetime": datetime(2026, 8, 31) + timedelta(days=day, hours=17),
        "day_index": day,
        "shift": shift,
        "encounter": _ENC,
        "roster_map": {},
        "vitals": [],
        "medications": [],
        "nursing_risk_assessments": [],
        "patient": {"date_of_birth": "1950-01-01"},
        "disease_protocol": None,
        "author_practitioner_id": "",
        "intake_output_records": [],
        "devices": [],
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _note(ctx: SimpleNamespace) -> tuple[str, list[str]]:
    out = render_nursing_shift_note(ctx, SimpleNamespace())
    return out.raw_text, out.facts_used


_IO = {
    "date": "2026-08-31",
    "intake_iv_ml": 1000,
    "intake_oral_ml": 600,
    "intake_other_ml": 0,
    "output_urine_ml": 1100,
    "output_drain_ml": 0,
    "output_other_ml": 500,
    "net_balance_ml": 0,
}


def test_previous_day_balance_ja_en_and_fact() -> None:
    ja, facts = _note(_ctx("ja", 1, intake_output_records=[_IO]))
    assert "前日 (8/31) の水分出納: 摂取 1600 mL、排出 1600 mL (うち尿 1100 mL)、バランス +0 mL。" in ja
    assert "ctx.intake_output_records.previous_day" in facts
    en, _ = _note(_ctx("en", 1, intake_output_records=[{**_IO, "net_balance_ml": -250}]))
    assert "Previous day (8/31) fluid balance: intake 1600 mL, output 1600 mL (urine 1100 mL), net -250 mL." in en


def test_drain_is_named() -> None:
    ja, _ = _note(_ctx("ja", 1, intake_output_records=[{**_IO, "output_drain_ml": 120}]))
    assert "うち尿 1100 mL、ドレーン 120 mL" in ja


def test_io_only_the_previous_completed_day_never_the_shift_day() -> None:
    # Day 0: no previous-day record. Day 1 with only the same-day record: nothing.
    assert "水分出納" not in _note(_ctx("ja", 0, intake_output_records=[_IO]))[0]
    same_day = {**_IO, "date": "2026-09-01"}
    assert "水分出納" not in _note(_ctx("ja", 1, intake_output_records=[same_day]))[0]
    # A gap (the record of 2 days before) is not "the previous day".
    assert "水分出納" not in _note(_ctx("ja", 2, intake_output_records=[_IO]))[0]


def test_io_same_for_every_shift_of_the_day_and_never_shift_level() -> None:
    for shift in ("day", "evening", "night"):
        ja, _ = _note(_ctx("ja", 1, shift, intake_output_records=[_IO]))
        assert "前日 (8/31)" in ja


def test_io_skipped_for_empty_record_and_newborn() -> None:
    empty = {k: (v if k == "date" else 0) for k, v in _IO.items()}
    assert "水分出納" not in _note(_ctx("ja", 1, intake_output_records=[empty]))[0]
    baby = _ctx("ja", 1, intake_output_records=[_IO], patient={"date_of_birth": "2026-08-30"})
    assert "水分出納" not in _note(baby)[0]


def _cath(start: str = "2026-08-31T20:15:00", end: str | None = None) -> dict:
    return {"kind": "urinary_catheter", "start": start, "end_date": end, "source": "procedure"}


def test_catheter_in_place_from_insertion_until_removal() -> None:
    dev = [_cath(end="2026-09-02")]
    # Inserted 20:15 on day 0: not in the day shift of day 0 (authored 17:00), in the night of day 0.
    assert "尿道留置カテーテル" not in _note(_ctx("ja", 0, "day", devices=dev))[0]
    ja, facts = _note(_ctx("ja", 1, "day", devices=dev))
    assert "尿道留置カテーテル留置中。固定状況、尿の流出と性状の観察を継続。" in ja
    assert "ctx.devices.shift" in facts
    assert "尿道留置カテーテル" in _note(_ctx("ja", 2, "day", devices=dev))[0]
    # Removed on 09-02: the day after has no mention.
    assert "尿道留置カテーテル" not in _note(_ctx("ja", 3, "day", devices=dev))[0]
    en, _ = _note(_ctx("en", 1, "day", devices=dev))
    assert "Indwelling urinary catheter in place;" in en


def test_central_line_and_oxygen_device() -> None:
    dev = [{"kind": "central_line", "start": "2026-08-31T10:00:00", "end_date": None, "source": "procedure"}]
    vitals = [
        {
            "timestamp": "2026-09-01T10:00:00",
            "on_supplemental_oxygen": True,
            "oxygen_delivery_device": "nasal_cannula",
            "oxygen_flow_rate_lpm": 2,
        }
    ]
    ja, _ = _note(_ctx("ja", 1, devices=dev, vitals=vitals))
    assert "中心静脈カテーテル留置中。" in ja
    assert "酸素: " in ja and "装着状態の観察を継続。" in ja
    off = [{**vitals[0], "on_supplemental_oxygen": False}]
    assert "装着状態" not in _note(_ctx("ja", 1, devices=dev, vitals=off))[0]


def test_phrases_exist_in_ja_and_en() -> None:
    for key in (
        "io.balance",
        "io.balance_drain",
        "devices.urinary_catheter",
        "devices.central_line",
        "devices.oxygen",
    ):
        for lang in ("ja", "en"):
            assert t(f"nursing_shift_items.{key}", lang) != f"nursing_shift_items.{key}"


def test_build_devices_sources_and_removal() -> None:
    record = {
        "extensions": {
            "device": [
                {
                    "encounter_id": "E1",
                    "device_type": "indwelling_catheter",
                    "placement_date": "2026-08-31",
                    "removal_date": "2026-09-05",
                },
                {"encounter_id": "OTHER", "device_type": "cvc", "placement_date": "2026-08-31", "removal_date": None},
            ]
        },
        "procedures": [
            {"encounter_id": "E1", "procedure_type": "urinary_catheter", "start_datetime": "2026-08-31T14:00:00"},
            {"encounter_id": "E1", "procedure_type": "central_line", "start_datetime": "2026-09-01T08:00:00"},
        ],
        "orders": [
            {
                "encounter_id": "E1",
                "display_name": "foley_catheter: Strict I/O",
                "ordered_datetime": "2026-08-31T13:50:00",
            },
            {
                "encounter_id": "E1",
                "display_name": "NPO: NPO until catheterization assessment",
                "ordered_datetime": "2026-08-31T09:00:00",
            },
        ],
    }
    devs = {d["kind"]: d for d in build_devices(record, _ENC)}
    # The urinary catheter starts at the earliest procedure / order time; the removal is the device record's.
    assert devs["urinary_catheter"]["start"] == "2026-08-31T13:50:00"
    assert devs["urinary_catheter"]["end_date"] == "2026-09-05"
    # The central line has the procedure only (the cvc device record belongs to another encounter): no removal known.
    assert devs["central_line"]["end_date"] is None and devs["central_line"]["source"] == "procedure"


def test_build_devices_order_only_and_cancelled_and_none() -> None:
    order = {
        "encounter_id": "E1",
        "display_name": "Foley catheter insertion",
        "ordered_datetime": "2026-08-31T13:50:00",
    }
    assert [d["source"] for d in build_devices({"orders": [order]}, _ENC)] == ["order"]
    assert build_devices({"orders": [{**order, "status": "cancelled"}]}, _ENC) == []
    assert build_devices({}, _ENC) == []


def test_device_record_alone_places_from_its_date() -> None:
    rec = {
        "extensions": {
            "device": [
                {
                    "encounter_id": "E1",
                    "device_type": "cvc",
                    "placement_date": "2026-08-31",
                    "removal_date": "2026-09-03",
                }
            ]
        }
    }
    (d,) = build_devices(rec, _ENC)
    assert d == {"kind": "central_line", "start": "2026-08-31T00:00:00", "end_date": "2026-09-03", "source": "device"}
