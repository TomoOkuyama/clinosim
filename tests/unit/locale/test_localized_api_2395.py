"""One retrieval API with one fallback order: requested language, then
English, then the caller's explicit fallback (Issue #2395)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from clinosim.locale.i18n import _load_phrase_catalog, t
from clinosim.locale.loaders.narrative import resolve_localized_display
from clinosim.locale.localized import label, localized, localized_field, normalize_lang
from clinosim.locale.text import resolve_text
from clinosim.modules._shared import pick_localized_field

pytestmark = pytest.mark.unit

_ENTRY = {"en": "Chest pain", "ja": "胸痛"}
_JA_ONLY = {"ja": "胸痛"}


@pytest.mark.parametrize(("lang", "code"), [("ja", "ja"), ("JA", "ja"), ("JP", "ja"), ("us", "en"), ("", "en")])
def test_normalize_lang(lang: str, code: str) -> None:
    assert normalize_lang(lang) == code


def test_localized_order() -> None:
    assert localized(_ENTRY, "ja") == "胸痛"
    assert localized(_ENTRY, "fr") == "Chest pain"  # English, not another language
    assert localized(_JA_ONLY, "en", fallback="x") == "x"  # never Japanese for English output
    assert localized(_JA_ONLY, "fr") == ""
    assert localized("Chest pain", "ja") == "Chest pain"  # a bare string is language-neutral
    assert localized(None, "ja", fallback="x") == "x"


def test_localized_field_order() -> None:
    rec = {"findings": "Normal", "findings_ja": "正常"}
    assert localized_field(rec, "findings", "ja") == "正常"
    assert localized_field(rec, "findings", "fr") == "Normal"
    assert localized_field(SimpleNamespace(findings_ja="正常", findings=""), "findings", "en", fallback="-") == "-"
    assert localized_field({"title_en": "Plan", "title_ja": "計画"}, "title", "en") == "Plan"


def test_label() -> None:
    catalog = {"severity": {"mild": {"en": "mild", "ja": "軽症"}}}
    assert label(catalog, "severity", "mild", "JP") == "軽症"
    assert label(catalog, "severity", "unknown", "ja", fallback="?") == "?"


@pytest.mark.parametrize(
    "call",
    [
        lambda e, lang, fb: resolve_localized_display(e, lang, fb),
        lambda e, lang, fb: resolve_text(e, lang) or fb,
    ],
)
def test_existing_helpers_follow_the_order(call: Any) -> None:
    assert call(_ENTRY, "jp", "fb") == "胸痛"
    assert call(_ENTRY, "fr", "fb") == "Chest pain"
    assert call(_JA_ONLY, "en", "fb") == "fb"  # resolve_text used to return the first value


def test_pick_localized_field_delegates() -> None:
    assert pick_localized_field({"x": "a", "x_ja": "あ"}, "x", "ja") == "あ"
    assert pick_localized_field({"x_ja": "あ"}, "x", "en", fallback="-") == "-"


def test_t_never_echoes_the_key() -> None:
    assert t("does.not.exist", "en") == ""


def _leaves(node: Any, path: str = ""):
    if isinstance(node, dict) and node and all(isinstance(v, str) for v in node.values()):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _leaves(v, f"{path}.{k}" if path else str(k))


def test_every_phrase_has_english() -> None:
    """With no key echo, a phrase without English would render empty."""
    missing = [p for p, leaf in _leaves(_load_phrase_catalog()) if not leaf.get("en")]
    assert not missing, missing[:20]
