from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.template_generator import _pick_localized


@pytest.mark.unit
def test_pick_localized_returns_en_for_en_lang():
    t = SimpleNamespace(hpi_en="english hpi", hpi_ja="ja hpi")
    assert _pick_localized(t, "hpi", "en") == "english hpi"


@pytest.mark.unit
def test_pick_localized_returns_ja_for_ja_lang():
    t = SimpleNamespace(hpi_en="english hpi", hpi_ja="ja hpi")
    assert _pick_localized(t, "hpi", "ja") == "ja hpi"


@pytest.mark.unit
def test_pick_localized_missing_returns_empty_and_warns(caplog):
    t = SimpleNamespace(hpi_ja="ja hpi")  # no _en
    with caplog.at_level("WARNING"):
        result = _pick_localized(t, "hpi", "en")
    assert result == ""
    assert any("hpi_en" in rec.message for rec in caplog.records)


@pytest.mark.unit
def test_pick_localized_dict_access():
    t = {"hpi_en": "english", "hpi_ja": "ja"}
    assert _pick_localized(t, "hpi", "en") == "english"


@pytest.mark.unit
def test_pick_localized_none_input():
    assert _pick_localized(None, "hpi", "en") == ""
