"""The free-text name translator lives in the locale layer (Issue #2367)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import clinosim
from clinosim.locale import free_text
from clinosim.modules.output.fhir_r4.lib import localization

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent


def test_no_module_outside_fhir_imports_the_fhir_localizer() -> None:
    pattern = re.compile(
        r"from clinosim\.modules\.output\.fhir_r4\.lib\.localization import|fhir_r4\.lib import localization"
    )
    offenders = [
        p.relative_to(_ROOT).as_posix()
        for p in _ROOT.rglob("*.py")
        if not p.relative_to(_ROOT).as_posix().startswith("modules/output/fhir_r4/")
        and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders


def test_no_lazy_localizer_thunks_remain() -> None:
    assert not [p for p in _ROOT.rglob("*.py") if "_load_drug_localizer" in p.read_text(encoding="utf-8")]


def test_fhir_layer_reexports_the_same_functions() -> None:
    assert localization._localize_drug_name is free_text._localize_drug_name
    assert localization.localize_drug_name is free_text.localize_drug_name


@pytest.mark.parametrize(
    ("text", "lang", "expected"), [("Warfarin", "ja", "ワルファリン"), ("Warfarin", "en", "Warfarin")]
)
def test_localize_free_text(text: str, lang: str, expected: str) -> None:
    assert free_text.localize_free_text(text, lang) == expected
