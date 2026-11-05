"""Issue #2650: a treatment named in note text never shows its internal slug."""

from __future__ import annotations

import re

import pytest

from clinosim.locale.free_text import localize_drug_name

pytestmark = pytest.mark.unit

_SLUG = re.compile(r"\b[A-Za-z]+_[A-Za-z_]+\b")


@pytest.mark.parametrize(
    ("name", "en"),
    [
        ("IV_fluid: Crystalloid 30 mL/kg bolus within 3 hours", "IV fluids: Crystalloid 30 mL/kg bolus within 3 hours"),
        ("pain_management: Acetaminophen 1 g IV q6h", "pain management: Acetaminophen 1 g IV q6h"),
        ("K_replace: KCl 20 mEq IV", "potassium replacement: KCl 20 mEq IV"),
        ("DVT_prophylaxis: Enoxaparin 40 mg SC daily", "DVT prophylaxis: Enoxaparin 40 mg SC daily"),
    ],
)
def test_english_names_a_treatment_for_a_reader(name: str, en: str) -> None:
    assert localize_drug_name(name, "en") == en


@pytest.mark.parametrize("name", ["IV_fluid: NS 80 mL/h", "pain_management: Acetaminophen", "K_replace: KCl 20 mEq"])
def test_japanese_has_no_slug_either(name: str) -> None:
    assert not _SLUG.search(localize_drug_name(name, "ja"))


def test_a_plain_drug_name_is_unchanged_in_english() -> None:
    assert localize_drug_name("Ceftriaxone 1 g IV q24h", "en") == "Ceftriaxone 1 g IV q24h"
