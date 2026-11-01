"""Each kind of name has its own resolver and table (Issue #2408)."""

from __future__ import annotations

import pytest

from clinosim.locale.free_text import (
    localize_allergen_name,
    localize_drug_name,
    localize_free_text,
    localize_procedure_name,
)
from clinosim.locale.loader import (
    load_allergen_display_dict,
    load_drug_display_dict,
    load_narrative_display_dict,
    load_procedure_display_dict,
)

pytestmark = pytest.mark.unit


def test_drug_resolver_does_not_use_procedure_names() -> None:
    assert "sequential compression devices" not in load_drug_display_dict()
    assert localize_drug_name("Sequential compression devices", "ja") == "Sequential compression devices"
    assert localize_procedure_name("Sequential compression devices", "ja") == "間欠的空気圧迫装置"


def test_each_kind_resolves_its_own_names() -> None:
    assert localize_drug_name("Heparin", "ja") == "ヘパリン"
    assert localize_allergen_name("Penicillin", "ja") == "ペニシリン"
    assert localize_allergen_name("Unknown substance", "ja") == "Unknown substance"


def test_free_text_uses_every_table() -> None:
    merged = load_narrative_display_dict()
    for table in (load_drug_display_dict(), load_procedure_display_dict(), load_allergen_display_dict()):
        assert set(table) <= set(merged)
    assert localize_free_text("Ice pack application", "ja") == "氷嚢貼付"


@pytest.mark.parametrize(
    "resolver", [localize_drug_name, localize_procedure_name, localize_allergen_name, localize_free_text]
)
def test_english_is_returned_unchanged(resolver) -> None:  # type: ignore[no-untyped-def]
    assert resolver("Ice pack application", "en") == "Ice pack application"
