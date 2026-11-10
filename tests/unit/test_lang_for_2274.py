"""One case-insensitive country -> language / key derivation (Issue #2274)."""

from __future__ import annotations

import pytest

from clinosim.codes import lookup
from clinosim.countries import country_slot, lang_for
from clinosim.locale.text import resolve_text
from clinosim.modules.disease.localization import _country_to_yaml_key

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("country", "lang"),
    [("JP", "ja"), ("jp", "ja"), (" Jp ", "ja"), ("US", "en"), ("us", "en"), ("FR", "en"), ("", "en")],
)
def test_lang_for(country: str, lang: str) -> None:
    assert lang_for(country) == lang


@pytest.mark.parametrize(
    ("country", "code", "legacy"),
    [("JP", "jp", "japan"), ("jp", "jp", "japan"), ("US", "us", "us")],
)
def test_country_slot(country: str, code: str, legacy: str) -> None:
    assert country_slot(country) == code
    assert country_slot(country, scheme="legacy_japan") == legacy


def test_country_slot_of_a_country_without_a_profile_raises() -> None:
    # Issue #3143: no silent US slot for an unknown country.
    with pytest.raises(KeyError):
        country_slot("FR")


def test_former_copies_are_case_insensitive() -> None:
    assert resolve_text({"en": "Chest pain", "ja": "胸痛"}, country="jp") == "胸痛"
    assert lookup("snomed-ct", "387713003", lang_for("jp")) == lookup("snomed-ct", "387713003", lang_for("JP"))
    assert _country_to_yaml_key("jp") == "japan"
