"""Issue #3837: the Assessment of an OSA follow-up states the CPAP therapy the
follow-up is for (no AHI or adherence figure the record does not hold)."""

from __future__ import annotations

import pytest

from tests.unit.modules.document.test_chronic_assessment_structured_fallback_1776 import _mk_ctx, _run

pytestmark = pytest.mark.unit


def test_osa_assessment_states_cpap_therapy_en() -> None:
    text = _run(_mk_ctx("G47.30", ""))
    assert "CPAP therapy continued." in text, text
    assert "problem list" not in text


def test_osa_assessment_states_cpap_therapy_ja() -> None:
    assert "CPAP 療法を継続。" in _run(_mk_ctx("G47.30", "", lang="ja"))


def test_other_condition_is_unchanged() -> None:
    assert "CPAP" not in _run(_mk_ctx("J30.9", ""))
