"""A fixed vital statement of an ED encounter template's exam (ankle sprain:
"心拍数正常", "Respiratory rate normal") is left out when the arrival reading
contradicts it (Issue #3235)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_physical_exam
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from tests.unit.modules.document.narrative.test_ed_note_admitted_hpi_exam_3243 import _ARRIVAL, _ctx, _vital

pytestmark = pytest.mark.unit

_TEMPLATE = SimpleNamespace(
    physical_exam={
        "en": {
            "general": "Alert and oriented",
            "cardiovascular": "Heart rate normal",
            "respiratory": "Respiratory rate normal",
        },
        "ja": {"general": "意識清明", "cardiovascular": "心拍数正常", "respiratory": "呼吸数正常"},
    }
)


def _exam(lang: str, **vital: float) -> str:
    gen = TemplateNarrativeGenerator()
    ctx = _ctx(None, lang, enc_type="emergency", vitals=[_vital(_ARRIVAL, **vital)])
    with patch.object(gen, "_get_ed_note_template", return_value=_TEMPLATE):
        return build_ed_physical_exam(gen, ctx)[0]


@pytest.mark.parametrize(("lang", "hr_text"), [("ja", "心拍数正常"), ("en", "Heart rate normal")])
def test_heart_rate_statement_follows_the_arrival_reading(lang: str, hr_text: str) -> None:
    assert hr_text in _exam(lang, heart_rate=80)
    assert hr_text not in _exam(lang, heart_rate=107)


@pytest.mark.parametrize(("lang", "rr_text"), [("ja", "呼吸数正常"), ("en", "Respiratory rate normal")])
def test_respiratory_rate_statement_follows_the_arrival_reading(lang: str, rr_text: str) -> None:
    assert rr_text in _exam(lang, respiratory_rate=16)
    assert rr_text not in _exam(lang, respiratory_rate=28)
