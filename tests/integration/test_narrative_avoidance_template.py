"""Template fallback renders drug-safety avoidance in progress-note Plan section (JA + EN)."""

from __future__ import annotations

from clinosim.modules.document.narrative.template_generator import (
    _render_safety_skips_line,
)


def _skip(
    considered: str,
    considered_ja: str,
    avoided: str,
    avoided_ja: str,
    substituted: str | None = None,
    substituted_ja: str | None = None,
) -> dict:
    return {
        "considered": considered,
        "considered_ja": considered_ja,
        "avoided_due_to": avoided,
        "avoided_due_to_ja": avoided_ja,
        "substituted_with": substituted,
        "substituted_with_ja": substituted_ja,
        "context": "pain_management",
        "severity": "contraindicated",
        "rationale_en": "risk",
        "rationale_ja": "リスク",
    }


def test_ja_renders_avoidance_with_substitution() -> None:
    skips = [
        _skip(
            "Ibuprofen",
            "イブプロフェン",
            "Warfarin",
            "ワルファリン",
            "Acetaminophen",
            "アセトアミノフェン",
        )
    ]
    out = _render_safety_skips_line(skips, "ja")
    assert "イブプロフェン" in out
    assert "ワルファリン" in out
    assert "アセトアミノフェン" in out
    assert "回避" in out


def test_ja_renders_avoidance_without_substitution() -> None:
    skips = [_skip("Ibuprofen", "イブプロフェン", "Warfarin", "ワルファリン")]
    out = _render_safety_skips_line(skips, "ja")
    assert "イブプロフェン" in out
    assert "処方せず" in out


def test_en_renders_avoidance_with_substitution() -> None:
    skips = [
        _skip(
            "Ibuprofen",
            "イブプロフェン",
            "Warfarin",
            "ワルファリン",
            "Acetaminophen",
            "アセトアミノフェン",
        )
    ]
    out = _render_safety_skips_line(skips, "en")
    assert "Ibuprofen" in out
    assert "Warfarin" in out
    assert "Acetaminophen" in out
    assert "avoided" in out


def test_empty_skips_yields_empty_string() -> None:
    assert _render_safety_skips_line([], "ja") == ""
    assert _render_safety_skips_line([], "en") == ""


def test_multiple_skips_produce_multiple_lines() -> None:
    skips = [
        _skip("Ibuprofen", "イブプロフェン", "Warfarin", "ワルファリン", "Acetaminophen", "アセトアミノフェン"),
        _skip("Naproxen", "ナプロキセン", "Apixaban", "アピキサバン"),
    ]
    out_ja = _render_safety_skips_line(skips, "ja")
    assert len(out_ja.splitlines()) == 2
    out_en = _render_safety_skips_line(skips, "en")
    assert len(out_en.splitlines()) == 2
