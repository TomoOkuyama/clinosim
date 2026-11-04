from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.template_generator import _pick_localized


@pytest.mark.unit
def test_pick_localized_returns_the_authored_language():
    t = SimpleNamespace(hpi={"en": "english hpi", "ja": "ja hpi"})
    assert _pick_localized(t, "hpi", "ja") == "ja hpi"


@pytest.mark.unit
def test_pick_localized_returns_en_for_en_lang():
    t = SimpleNamespace(hpi={"en": "english hpi", "ja": "ja hpi"})
    assert _pick_localized(t, "hpi", "en") == "english hpi"


@pytest.mark.unit
def test_pick_localized_never_falls_back_to_another_language():
    """A template is used in exactly the requested language (Issue #2507)."""
    t = SimpleNamespace(hpi={"ja": "ja hpi"})
    assert _pick_localized(t, "hpi", "en") == ""


@pytest.mark.unit
def test_pick_localized_missing_authored_language_returns_empty_and_warns(caplog):
    t = SimpleNamespace(hpi={"en": "english hpi"})  # no ja
    with caplog.at_level("WARNING"):
        result = _pick_localized(t, "hpi", "ja")
    assert result == ""
    assert any("hpi.ja" in rec.message for rec in caplog.records)


@pytest.mark.unit
def test_pick_localized_dict_access():
    t = {"hpi": {"en": "english", "ja": "ja"}}
    assert _pick_localized(t, "hpi", "ja") == "ja"


@pytest.mark.unit
def test_pick_localized_none_input():
    assert _pick_localized(None, "hpi", "en") == ""
