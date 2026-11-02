"""SNOMED internal-key maps live in snomed-maps.yaml; no SNOMED literals in
emitters (Issue #2379)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clinosim.codes.snomed import snomed_display, snomed_for, snomed_map
from clinosim.datafiles import load_data_yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3] / "clinosim"
_KINDS = tuple(load_data_yaml(_ROOT / "codes" / "data" / "snomed-maps.yaml"))


@pytest.mark.parametrize("kind", _KINDS)
def test_every_mapped_code_is_registered_with_english(kind: str) -> None:
    assert not sorted(code for code in snomed_map(kind).values() if not snomed_display(code, "en"))


@pytest.mark.parametrize(
    ("kind", "key", "code"),
    [
        ("abo", "AB", "165742001"),
        ("rh", "positive", "165747007"),
        ("rh", "-", "165748002"),
        ("cchd_site", "right_hand", "368209003"),  # right, not left (#1815)
        ("cchd_site", "foot", "56459004"),
        ("encounter_type", "outpatient", "270427003"),
        ("oxygen_device", "nasal_cannula", "336623009"),
        ("stage", "CKD G3a", "700378005"),
        ("procedure_category", "evaluation", "386053000"),
        ("newborn_screen", "hearing_aabr", "413083006"),
        ("newborn_screen", "metabolic", "428447008"),
    ],
)
def test_snomed_for(kind: str, key: str, code: str) -> None:
    assert snomed_for(kind, key) == code


def test_unknown_key_is_none() -> None:
    assert snomed_for("abo", "Z") is None
    assert snomed_for("cchd_site", "left_hand") is None


def test_the_mapper_modules_are_gone() -> None:
    assert not list((_ROOT / "codes").glob("*_to_snomed.py"))


def test_no_snomed_uri_literal_outside_codes() -> None:
    offenders = [
        str(p.relative_to(_ROOT))
        for p in _ROOT.rglob("*.py")
        if "snomed.info/sct" in p.read_text(encoding="utf-8") and not str(p.relative_to(_ROOT)).startswith("codes/")
    ]
    assert not offenders


@pytest.mark.parametrize(
    "rel",
    ["modules/output/fhir_r4/post_process/specimen.py", "modules/output/fhir_r4/labs/service_request.py"],
)
def test_emitter_has_no_snomed_code_literal(rel: str) -> None:
    src = (_ROOT / rel).read_text(encoding="utf-8")
    assert not re.search(r'_SNOMED[A-Z_]* = "\d{6,}"', src)
