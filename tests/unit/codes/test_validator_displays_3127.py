"""Code displays the FHIR validator accepts (Issue #3127): each display is the
code system's own display, and a procedure body site names the intended site."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes import display

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3] / "clinosim"


@pytest.mark.parametrize(
    ("system", "code", "lang", "expected"),
    [
        ("icd-10-cm", "J18.9", "en", "Pneumonia, unspecified organism"),
        ("icd-10-cm", "N10", "en", "Acute pyelonephritis"),
        ("loinc", "2324-2", "en", "Gamma glutamyl transferase [Enzymatic activity/volume] in Serum or Plasma"),
        ("loinc", "3016-3", "en", "Thyrotropin [Units/volume] in Serum or Plasma"),
        ("loinc", "2093-3", "en", "Cholesterol [Mass/volume] in Serum or Plasma"),
        (
            "loinc",
            "48642-3",
            "en",
            "Glomerular filtration rate [Volume Rate/Area] in Serum, Plasma or Blood by Creatinine-based "
            "formula (MDRD)/1.73 sq M among non black population",
        ),
        ("yj", "1141007F3023", "ja", "カロナール錠５００"),
    ],
)
def test_display_is_the_code_systems_display(system: str, code: str, lang: str, expected: str) -> None:
    assert display(system, code, lang) == expected


@pytest.mark.parametrize(
    ("procedure", "site", "site_display"),
    [
        ("iv_line", "421466002", "Structure of peripheral vein"),
        ("arterial_line", "45631007", "Structure of radial artery"),
        ("thoracentesis", "91381003", "Pleural cavity structure"),
        ("lumbar_puncture", "122496007", "Lumbar spine structure"),
        ("wound_care", "127856007", "Skin and/or subcutaneous tissue structure"),
        ("ileus_tube_placement", "30315005", "Structure of small intestine"),
        ("bowel_resection", "14742008", "Structure of large intestine"),
    ],
)
def test_procedure_body_site_names_the_intended_site(procedure: str, site: str, site_display: str) -> None:
    meta = yaml.safe_load((_ROOT / "codes/data/procedure-snomed-metadata.yaml").read_text(encoding="utf-8"))
    assert meta["procedures"][procedure]["body_site"] == site
    assert display("snomed-ct", site, "en") == site_display


def test_surgical_site_infection_complication_code() -> None:
    meta = yaml.safe_load((_ROOT / "codes/data/procedure-snomed-metadata.yaml").read_text(encoding="utf-8"))
    assert meta["complications"]["surgical_site_infection"] == "433202001"
    assert display("snomed-ct", "433202001", "en") == "Surgical site infection"
