"""Issue #2664: a culture report's text form names the specimen and the antibiotics."""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.labs.microbiology import _mb_presented_text

pytestmark = pytest.mark.unit

_MB = {
    "specimen": "urine",
    "specimen_snomed": "122575003",
    "growth": True,
    "organism_snomed": "78065002",  # Enterococcus faecalis
    "susceptibilities": [
        {"antibiotic_loinc": "18864-9", "interpretation": "S"},
        {"antibiotic_loinc": "19000-9", "interpretation": "R"},
    ],
}


@pytest.mark.parametrize(
    ("lang", "words"),
    [
        ("ja", ["尿検体", "アンピシリン", "感性", "バンコマイシン", "耐性"]),
        ("en", ["Urine specimen", "Ampicillin", "Susceptible", "Vancomycin", "Resistant"]),
    ],
)
def test_the_text_form_is_readable(lang: str, words: list[str]) -> None:
    text = _mb_presented_text(_MB, lang)
    for w in words:
        assert w in text, (w, text)
    assert "urine" not in text.split("\n")[0].split(":", 1)[1].lower().replace("urine specimen", "")
    assert not re.search(r"\b\d{4,5}-\d\b", text)
