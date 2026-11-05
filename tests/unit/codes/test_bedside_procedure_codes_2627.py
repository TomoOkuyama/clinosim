"""Issue #2627: every bedside procedure is coded and named for a reader."""

from __future__ import annotations

import pytest

from clinosim.codes import display as registry_display
from clinosim.codes.snomed import snomed_for_phrase
from clinosim.locale.free_text import localize_procedure_name

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("name", "code", "display"),
    [
        ("Nasal packing (anterior)", "365958005", "Packing of anterior nasal cavity"),
        ("Skin staples", "50015006", "Closure by staple"),
        ("Posterior splint", "79321009", "Application of splint"),
        ("Short arm splint", "439535000", "Application of short arm splint"),
        ("Short arm cast", "438409006", "Application of short arm cast"),
        ("Silver nitrate cauterization", "135871000", "Silver nitrate cautery"),
        ("IV_access: Peripheral IV line", "233520008", "Insertion of peripheral venous cannula into peripheral vein"),
    ],
)
def test_a_bedside_procedure_is_coded_in_snomed_ct(name: str, code: str, display: str) -> None:
    assert snomed_for_phrase(name) == code
    assert registry_display("snomed-ct", code, "en") == display
    assert registry_display("snomed-ct", code, "ja")


def test_an_iv_access_order_is_named_for_a_reader() -> None:
    assert localize_procedure_name("IV_access: Peripheral IV line", "en") == "IV access: Peripheral IV line"
    assert "_" not in localize_procedure_name("IV_access: Peripheral IV line", "ja")
    assert "access" not in localize_procedure_name("IV_access: Peripheral IV line", "ja")
