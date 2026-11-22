"""ED exam phrases follow the record (Issue #3569): the heart-rate statement
matches the arrival reading, every abdominal finding is labelled, a visit that
does not assess the abdomen omits it, and one oxygen flow unit is used per
note language."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_physical_exam
from clinosim.modules.encounter.protocol import load_all_encounter_conditions, load_encounter_condition
from tests.unit.modules.document.narrative.test_ed_note_protocol_2871 import _GEN, _ctx

pytestmark = pytest.mark.unit


def _exam(condition: str, lang: str, hr: float | None) -> str:
    ctx = _ctx(condition, lang)
    if hr is not None:
        ctx.vitals = [SimpleNamespace(timestamp=datetime(2026, 1, 1, 10), heart_rate=hr)]
    text, _ = build_ed_physical_exam(_GEN, ctx)
    return text


@pytest.mark.parametrize("condition", ["viral_uri", "abdominal_pain_nonspecific", "ankle_sprain"])
def test_heart_rate_statement_follows_recorded_rate_ja(condition: str) -> None:
    normal = _exam(condition, "ja", 66)
    assert "心拍数正常" in normal and "軽度頻脈" not in normal
    fast = _exam(condition, "ja", 130)
    assert "頻脈" in fast and "心拍数正常" not in fast
    slow = _exam(condition, "ja", 40)
    assert "徐脈" in slow


@pytest.mark.parametrize("condition", ["viral_uri", "abdominal_pain_nonspecific", "ankle_sprain"])
def test_heart_rate_statement_follows_recorded_rate_en(condition: str) -> None:
    assert "mildly tachycardic" not in _exam(condition, "en", 66)
    assert "heart rate normal" in _exam(condition, "en", 66)
    assert "tachycardic" in _exam(condition, "en", 130)


def test_ankle_sprain_omits_the_abdomen() -> None:
    for lang in ("ja", "en"):
        text = _exam("ankle_sprain", lang, 70)
        assert "評価不要" not in text and "not indicated" not in text
        assert "腹部" not in text and "Abdomen" not in text


def test_every_abdominal_finding_is_labelled() -> None:
    for cid, protocol in load_all_encounter_conditions().items():
        exams = (protocol.get("narrative") or {}).get("ed_note_template", {}).get("physical_exam") or {}
        for lang, label in (("ja", "腹部"), ("en", "Abdomen")):
            text = (exams.get(lang) or {}).get("abdominal")
            if text:
                assert text.startswith(label), (cid, lang, text)


def test_protocols_load_without_range_phrase() -> None:
    for cid in ("viral_uri", "abdominal_pain_nonspecific"):
        blob = str(load_encounter_condition(cid))
        assert "軽度頻脈" not in blob and "mildly tachycardic" not in blob


def test_elastic_bandage_phrase_is_complete() -> None:
    from clinosim.locale.free_text import lookup_procedure_phrase

    assert lookup_procedure_phrase("Elastic bandage wrap", "ja") == "弾性包帯固定"


def test_oxygen_flow_unit_is_one_form_per_language() -> None:
    ja = t("nursing_shift.o2_device_with_flow", "ja", device="酸素マスク", flow="5")
    assert "L/分" in ja and "L/min" not in ja
    en = t("nursing_shift.o2_device_with_flow", "en", device="mask", flow="5")
    assert "L/min" in en and "L/分" not in en


def test_no_japanese_phrase_uses_the_english_flow_unit() -> None:
    from pathlib import Path

    import yaml

    import clinosim.locale as locale_pkg

    data = yaml.safe_load((Path(locale_pkg.__file__).parent / "shared" / "narrative_phrases.yaml").read_text("utf-8"))

    def ja_texts(node: object) -> list[str]:
        if isinstance(node, dict):
            out = [v for k, v in node.items() if k == "ja" and isinstance(v, str)]
            for v in node.values():
                out += ja_texts(v)
            return out
        return []

    assert [x for x in ja_texts(data) if "L/min" in x] == []
