"""Chief complaint localization — Issue #1182.

`Encounter.chief_complaint` was emitting raw English ("Annual health
screening", "Mammography screening", "Post-discharge follow-up:
bacterial_pneumonia") on 20.9% of SOAP notes because the simulator's
visit_reason lookup returned bare English strings for screening,
pediatric fallback, and post-discharge fallback paths. On JP cohorts
this leaked to `chief_complaint_ja` and downstream SOAP subjective.

This test locks in the invariant: every simulator-side visit_reason
producer now returns either a bilingual dict or a JA string when the
country is JP, so `resolve_text(..., country="JP")` yields JA.
"""

from __future__ import annotations

from clinosim.locale.text import resolve_text
from clinosim.simulator.engine import (
    _HEALTH_SCREENING_VISIT_REASON,
    _HEALTH_SCREENING_VISIT_REASON_FALLBACK,
    _pediatric_visit_reason,
)


def _is_pure_ja(text: str) -> bool:
    """Loose check: no ASCII letters + non-empty."""
    return bool(text) and not any("a" <= c.lower() <= "z" for c in text)


def test_screening_visit_reasons_have_bilingual_dicts() -> None:
    for key, val in _HEALTH_SCREENING_VISIT_REASON.items():
        assert isinstance(val, dict)
        assert "en" in val and "ja" in val
        assert _is_pure_ja(val["ja"]), f"{key} JA leaks ASCII: {val['ja']!r}"


def test_screening_fallback_has_bilingual_dict() -> None:
    fb = _HEALTH_SCREENING_VISIT_REASON_FALLBACK
    assert isinstance(fb, dict)
    assert "en" in fb and "ja" in fb
    assert _is_pure_ja(fb["ja"])


def test_annual_health_screening_resolves_to_ja_for_jp() -> None:
    r = _HEALTH_SCREENING_VISIT_REASON["annual_health_screening"]
    assert resolve_text(r, country="JP") == "年次健診"
    assert resolve_text(r, country="US") == "Annual health screening"


def test_mammography_screening_resolves_to_ja_for_jp() -> None:
    r = _HEALTH_SCREENING_VISIT_REASON["mammography_screening"]
    assert resolve_text(r, country="JP") == "マンモグラフィー検診"


def test_pediatric_visit_reason_fallback_returns_bilingual_dict() -> None:
    # An unknown disease_id must return a bilingual dict, not a raw EN
    # `f"Pediatric visit: {disease_id}"` that would leak snake_case
    # into chief_complaint_ja.
    result = _pediatric_visit_reason("__unknown_disease_id__")
    assert isinstance(result, dict)
    assert "en" in result and "ja" in result
    assert _is_pure_ja(result["ja"])
    assert resolve_text(result, country="JP") == "小児外来受診"
