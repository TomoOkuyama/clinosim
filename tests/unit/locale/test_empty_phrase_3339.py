"""Issue #3339: an entry deliberately empty in a language is empty in that language.

A language slot present with ``""`` means "no text in this language" (Japanese
has no space after a full stop). Only an absent slot falls back to English
(code-mapping spec section 6).
"""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.locale.i18n import t
from clinosim.locale.loader import resolve_localized_display
from clinosim.locale.localized import label, localized
from clinosim.locale.table import LocalizedTable

pytestmark = pytest.mark.unit


def test_t_returns_intentionally_empty_ja_phrase_as_empty() -> None:
    assert t("list_sep.sentence_gap", "ja") == ""
    assert t("list_sep.chunk", "ja") == ""
    assert t("list_sep.sentence_gap", "en") == " "


def test_t_missing_language_still_falls_back_to_english() -> None:
    assert t("list_sep.sentence_gap", "fr") == " "
    assert t("list_sep.period_space", "fr") == ". "


def test_localized_empty_slot_is_returned_missing_slot_falls_back() -> None:
    entry = {"en": " ", "ja": ""}
    assert localized(entry, "ja") == ""
    assert localized(entry, "en") == " "
    assert localized({"en": "x"}, "ja") == "x"
    assert localized({"en": "x", "ja": None}, "ja") == "x"
    assert localized({}, "ja", fallback="fb") == "fb"
    assert resolve_localized_display(entry, "ja", fallback="fb") == ""
    assert label({"s": {"k": entry}}, "s", "k", "ja", fallback="fb") == ""


def test_localized_table_empty_slot_is_returned_missing_slot_falls_back() -> None:
    data: dict[str, Any] = {"gap": {"en": " ", "ja": ""}, "word": {"en": "w"}}
    table = LocalizedTable(name="t3339.gap", source=lambda: data)
    assert table.get("gap", "ja", fallback="fb") == ""
    assert table.get("gap", "en", fallback="fb") == " "
    assert table.get("word", "ja", fallback="fb") == "w"
