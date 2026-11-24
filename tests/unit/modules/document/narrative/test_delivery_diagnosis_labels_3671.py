"""Issue #3671: the assessment of a delivery H&P names a complication by its
display name (not a raw lower-case ICD code), writes no severity the record
does not hold, and does not list the birth-outcome code (Z37.*) as a working
diagnosis."""

from __future__ import annotations

import re

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.assessment_and_plan import (
    _compose_ap_assessment_from_state,
)
from tests.unit.modules.document.narrative.test_admission_hp_complete_3245 import _delivery_ctx

pytestmark = pytest.mark.unit
_RAW = re.compile(r"\b[zo]\d\d(\.\d)?\b", re.I)


def _assessment(lang: str, complications: list[str]) -> str:
    ctx = _delivery_ctx(lang, complications[0] if complications else "O80")
    ctx.principal_disease_id = "Z37.0"
    ctx.co_disease_ids = list(complications)
    return _compose_ap_assessment_from_state(ctx)


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_complication_is_named_without_raw_code_or_empty_severity(lang: str) -> None:
    text = _assessment(lang, ["O14.9", "O42.9"])
    assert not _RAW.search(text), text
    assert "severity: )" not in text and "()" not in text and "（）" not in text
    assert "moderate" not in text and "中等度" not in text, text


def test_english_names() -> None:
    text = _assessment("en", ["O14.9"])
    assert "pre-eclampsia" in text.lower(), text
    assert "single" not in text.lower()  # the birth outcome is not a working diagnosis


def test_japanese_names() -> None:
    text = _assessment("ja", ["O14.9"])
    assert "妊娠高血圧腎症" in text, text


def test_a_disease_with_a_severity_still_prints_it() -> None:
    from clinosim.modules.document.narrative.renderers.section_builders import assessment_and_plan as ap

    ctx = _delivery_ctx("en", "O80")
    ctx.principal_disease_id = "sepsis"
    ctx.severity = "severe"
    text = ap._compose_ap_assessment_from_state(ctx)
    assert "(severity: severe)" in text, text
