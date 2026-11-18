"""Newborn progress-note subjective and discharge instructions (Issue #3260).

A newborn's progress-note subjective is the day of life, feeding and
elimination and the jaundice review of the bilirubin measured by the note's
time (not the adult stable-day pool, which speaks of rehabilitation and
discharge training); its discharge instructions are written to the parents
(feeding, diapers, jaundice, safe sleep, cord care, follow-up), not the adult
baseline (drink plenty of fluids, take all medications by mouth).
"""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from clinosim.modules.document.narrative.renderers._composers import compose_progress_subjective_from_state
from clinosim.modules.document.narrative.renderers._resolvers import resolve_discharge_instructions
from clinosim.types.document import DocumentType
from tests.unit.modules.document.narrative.test_newborn_documents_3260 import _ctx

pytestmark = pytest.mark.unit

_CJK = re.compile(r"[぀-ヿ㐀-鿿]")


def _progress(lang: str, day: int = 2, **kw):
    ctx = _ctx(lang, day_index=day, authored=datetime(2026, 1, 26 + day, 12, 0), **kw)
    ctx.document_type = DocumentType.PROGRESS_NOTE
    return ctx


def test_newborn_subjective_ja_has_feeding_elimination_and_jaundice() -> None:
    text = compose_progress_subjective_from_state(_progress("ja", day=2))
    assert "日齢2" in text and "哺乳良好" in text and "排尿・排便" in text
    assert "総ビリルビン 8.8 mg/dL" in text
    assert "自立訓練" not in text and "リハビリ" not in text


def test_newborn_subjective_en_has_no_japanese_and_no_adult_pool() -> None:
    text = compose_progress_subjective_from_state(_progress("en", day=3))
    assert "Day of life 3" in text and "Feeding well" in text and "12.2 mg/dL" in text
    assert not _CJK.search(text)
    assert "rehab" not in text.lower() and "discharge" not in text.lower()


def test_newborn_subjective_without_a_bilirubin_yet_has_no_jaundice_claim() -> None:
    ctx = _progress("ja", day=1)
    ctx.authored_datetime = datetime(2026, 1, 27, 8, 0)
    assert "ビリルビン" not in compose_progress_subjective_from_state(ctx)


def test_adult_subjective_still_uses_the_stable_day_pool() -> None:
    ctx = _progress("ja", day=3, adult=True)
    assert "日齢" not in compose_progress_subjective_from_state(ctx)


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_newborn_discharge_instructions_are_for_the_parents(lang: str) -> None:
    ctx = _ctx(lang)
    entries = resolve_discharge_instructions(ctx)
    text = " ".join(e[lang] for e in entries.values())
    for adult in ("十分な水分摂取", "すべて指示通りに内服", "Drink plenty of fluids", "all prescribed medications"):
        assert adult not in text
    assert {"feeding", "voiding_stooling", "jaundice", "safe_sleep", "cord_care", "follow_up"} <= set(entries)
    if lang == "en":
        assert not _CJK.search(text)


def test_adult_discharge_instructions_keep_the_baseline() -> None:
    entries = resolve_discharge_instructions(_ctx("en", adult=True))
    assert "Drink plenty of fluids." in entries["hydrate"]["en"]
    assert "feeding" not in entries
