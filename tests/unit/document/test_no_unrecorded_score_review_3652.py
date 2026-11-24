"""Issue #3652: a note names a symptom-score or imaging review only when the visit has one."""

from __future__ import annotations

import re

import pytest

from clinosim.locale.i18n import t
from clinosim.locale.loaders.clinical import load_chronic_followup

SCORE_RE = re.compile(r"\b(CAT|mMRC|ACT|C-ACT)\b|Childhood ACT|スコア|コントロールテスト")
PHRASES = [
    "chronic_monitoring.cat_mmrc_review",
    "chronic_monitoring.act_control_review",
    "chronic_monitoring.cact_control_review",
    "chronic_monitoring.symptom_control_review",
]


@pytest.mark.parametrize("key", PHRASES)
@pytest.mark.parametrize("lang", ["en", "ja"])
def test_monitoring_phrase_claims_no_score(key: str, lang: str) -> None:
    text = t(key, lang)
    assert text and text != key
    assert not SCORE_RE.search(text), text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_japanese_phrases_are_japanese_and_english_ascii(lang: str) -> None:
    for key in PHRASES:
        text = t(key, lang)
        if lang == "ja":
            assert re.search(r"[぀-ヿ一-鿿]", text), text
        else:
            assert not re.search(r"[぀-ヿ一-鿿]", text), text


def test_post_pneumonia_reason_names_no_imaging() -> None:
    data = load_chronic_followup()
    entry = data["_post_discharge_by_disease"]["bacterial_pneumonia"]
    reason = entry["visit_reason"]
    assert "x-ray" not in reason["en"].lower()
    assert "X線" not in reason["ja"]
    assert "imaging" not in entry
