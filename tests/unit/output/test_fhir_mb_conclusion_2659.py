"""Issue #2659: a culture report's conclusion states every susceptibility."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.labs.microbiology import _mb_conclusion_text

pytestmark = pytest.mark.unit

_SUS = [
    ("18864-9", "R"),
    ("18895-3", "S"),
    ("18906-8", "R"),
    ("18928-2", "S"),
    ("18970-4", "S"),
    ("18943-1", "S"),
]


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_every_tested_antibiotic_is_in_the_conclusion(lang: str) -> None:
    mb = {
        "growth": True,
        "organism_snomed": "112283007",  # Escherichia coli
        "susceptibilities": [{"antibiotic_loinc": c, "interpretation": i} for c, i in _SUS],
    }
    text = _mb_conclusion_text(mb, lang)
    assert "…" not in text and "..." not in text
    assert text.count("=") == len(_SUS)
