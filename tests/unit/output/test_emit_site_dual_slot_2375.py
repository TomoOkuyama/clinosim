"""Coded concepts get their display and text at the emit site (Issue #2375)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.modules.output.fhir_r4.lib.common import build_diagnosis_codeable_concept
from clinosim.modules.output.fhir_r4.lib.dosage import build_route_concept

pytestmark = pytest.mark.unit

_POST = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "output" / "fhir_r4" / "post_process"


def test_text_filling_walkers_are_gone() -> None:
    src = "".join(p.read_text(encoding="utf-8") for p in _POST.glob("*.py"))
    assert "_copy_display_from_sibling_coding" not in src
    assert "_populate_cc_text_from_coding_lookup" not in src


def test_route_concept_has_english_coding_and_localized_text() -> None:
    concept = build_route_concept("PO", "JP")
    assert concept is not None
    assert concept["coding"][0]["display"].isascii()
    assert not concept["text"].isascii()


def test_diagnosis_concept_has_one_coding() -> None:
    concept = build_diagnosis_codeable_concept("I10", "icd-10-mhlw", "JP")
    assert len(concept["coding"]) == 1
    assert concept["text"]
