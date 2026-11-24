"""The JP easing sentence of the progress-note course line reads as Japanese
clinical writing, not a rendering of "improved, not yet sustained" (Issue #3704)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.locale.i18n import t

pytestmark = pytest.mark.unit

_YAML = Path(__file__).resolve().parents[5] / "clinosim" / "locale" / "shared" / "narrative_phrases.yaml"


def test_ja_easing_wording() -> None:
    text = t("progress.course_easing", "ja", list="SpO2 低下")
    assert text == "バイタルサインは前日より改善傾向 (SpO2 低下は改善しつつあるが、安定化は未確認)。"


def test_en_easing_unchanged() -> None:
    text = t("progress.course_easing", "en", list="low SpO2")
    assert text == "Vital signs improving compared with the previous day (low SpO2 improved, not yet sustained)."


def test_no_literal_translation_left_in_the_phrases() -> None:
    assert "持続は未確認" not in _YAML.read_text(encoding="utf-8")
