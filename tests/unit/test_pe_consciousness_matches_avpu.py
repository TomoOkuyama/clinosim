"""PE consciousness clause follows the day's recorded AVPU (#2086)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers._composers import apply_cc_pe_consistency

pytestmark = pytest.mark.unit

_TEXT = "一般状態: 意識清明、苦痛様。呼吸器: 肺音清明"


def _ctx(avpus: list[str], cc: str = "発熱") -> SimpleNamespace:
    adm = datetime(2026, 5, 1, 10, 0)
    enc = {"encounter_id": "E1", "chief_complaint_ja": cc, "admission_datetime": adm}
    vitals = [{"timestamp": datetime(2026, 5, 1, 12 + i, 0), "consciousness_level": a} for i, a in enumerate(avpus)]
    return SimpleNamespace(target_lang="ja", encounter=enc, vitals=vitals, day_index=0)


@pytest.mark.parametrize(("avpu", "marker"), [("V", "JCS I"), ("P", "JCS II"), ("U", "JCS III")])
def test_impaired_avpu_rewrites_alert_clause(avpu: str, marker: str) -> None:
    text, facts = apply_cc_pe_consistency(_TEXT, _ctx(["A", avpu]))
    assert "意識清明" not in text and marker in text
    assert "肺音清明" in text
    assert "avpu_pe_consistency:consciousness" in facts


def test_alert_day_keeps_clause() -> None:
    text, facts = apply_cc_pe_consistency(_TEXT, _ctx(["A", "A"]))
    assert text == _TEXT and not facts
