"""Issue #3664: the nursing shift notes of a delivery stay record the
postpartum observation (the obstetric finding of the delivery exam block, the
postpartum day) instead of only the stock sentence."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.nursing_shift_note import render_nursing_shift_note
from tests.unit.modules.document.narrative.test_nursing_shift_items_3478 import _ctx, _v

pytestmark = pytest.mark.unit

_BIRTH = SimpleNamespace(
    procedure_type="delivery",
    encounter_id="ENC-1",
    start_datetime="2026-08-31T12:00:00",
    end_datetime="2026-08-31T12:30:00",
)


def _note(lang: str, mode: str = "vaginal", authored: datetime | None = None, day: int = 0, **kw) -> str:
    ctx = _ctx(
        lang,
        [_v("14:00", heart_rate=80)],
        authored_datetime=authored or datetime(2026, 8, 31, 17, 0),
        day_index=day,
        delivery={"mode": mode},
        procedures=[_BIRTH],
        **kw,
    )
    ctx.encounter["encounter_id"] = "ENC-1"
    return render_nursing_shift_note(ctx, SimpleNamespace()).raw_text


def test_delivery_shift_note_has_fundus_and_lochia_and_no_stock_sentence_en() -> None:
    text = _note("en")
    assert "Postpartum day 0." in text and "fundus firm" in text and "lochia" in text, text
    assert "Observation and care ongoing" not in text
    assert "perineum" in text


def test_cesarean_shift_note_has_the_incision() -> None:
    assert "incision" in _note("en", "cesarean")


def test_delivery_shift_note_ja() -> None:
    text = _note("ja")
    assert "産褥0日" in text and "悪露" in text and "子宮底" in text, text
    assert "観察・ケア継続" not in text


def test_next_day_shift_counts_the_postpartum_day() -> None:
    assert "Postpartum day 1." in _note("en", authored=datetime(2026, 9, 1, 17, 0), day=1)


def test_breastfeeding_and_voiding_are_stated_as_not_recorded_not_asserted() -> None:
    text = _note("en")
    assert "not recorded" in text and "breastfeeding" in text.lower()
    assert "breastfeeding well" not in text.lower()


def test_shift_before_the_birth_ended_has_no_postpartum_item() -> None:
    text = _note("en", authored=datetime(2026, 8, 31, 12, 15))
    assert "Postpartum" not in text and "fundus" not in text


def test_other_inpatients_are_unchanged() -> None:
    ctx = _ctx("en", [_v("14:00", heart_rate=80)])
    text = render_nursing_shift_note(ctx, SimpleNamespace()).raw_text
    assert "Postpartum" not in text and "fundus" not in text
