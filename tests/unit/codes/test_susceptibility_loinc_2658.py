"""Issue #2658: each antibiotic is tested under its own susceptibility LOINC."""

from __future__ import annotations

import pytest

from clinosim.codes import display as registry_display
from clinosim.modules.observation.microbiology import antibiotic_loinc_lookup

pytestmark = pytest.mark.unit

# LOINC "<drug> [Susceptibility]" display, checked with tx.fhir.org CodeSystem/$lookup.
_LOINC_DRUG = {
    "ampicillin": "ampicillin",
    "cefazolin": "cefazolin",
    "ceftriaxone": "ceftriaxone",
    "cefepime": "cefepime",
    "ciprofloxacin": "ciprofloxacin",
    "gentamicin": "gentamicin",
    "vancomycin": "vancomycin",
    "piperacillin_tazobactam": "piperacillin+tazobactam",
    "meropenem": "meropenem",
    "trimethoprim_sulfamethoxazole": "trimethoprim+sulfamethoxazole",
}
_JA_DRUG = {
    "ampicillin": "アンピシリン",
    "cefazolin": "セファゾリン",
    "gentamicin": "ゲンタマイシン",
}


def test_every_antibiotic_code_names_that_antibiotic() -> None:
    codes = antibiotic_loinc_lookup()
    assert set(codes) == set(_LOINC_DRUG)
    for key, code in codes.items():
        en = registry_display("loinc", code, "en").lower()
        assert en == f"{_LOINC_DRUG[key]} [susceptibility]", (key, code, en)


@pytest.mark.parametrize("key", sorted(_JA_DRUG))
def test_the_japanese_display_names_the_same_antibiotic(key: str) -> None:
    code = antibiotic_loinc_lookup()[key]
    assert _JA_DRUG[key] in registry_display("loinc", code, "ja")
