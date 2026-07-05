"""_fhir_common.py's clinical short-name (code.text abbreviation) must
resolve via a new codes/data/condition-short-name.yaml + code_lookup, not
the hardcoded _CONDITION_SHORT_NAME dict (2026-07-02 grand design review,
display-dict migration — the largest/last item in this backlog).
"""

import pytest

from clinosim.codes import lookup
from clinosim.modules.output._fhir_common import _build_diagnosis_codeable_concept

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("code,en", [
    ("J44.9", "COPD"), ("I50.9", "Heart failure (CHF)"),
    ("N18.3", "CKD"), ("E11.9", "Type 2 diabetes (DM)"),
])
def test_short_name_us(code, en):
    concept = _build_diagnosis_codeable_concept(code, "icd-10-cm", "US")
    assert concept["text"] == en
    assert concept["text"] == lookup("condition-short-name", code.split(".")[0], "en")


@pytest.mark.parametrize("code,ja", [
    ("J44", "COPD（慢性閉塞性肺疾患）"), ("I50", "心不全"),
    ("N18", "慢性腎臓病"), ("E11", "2型糖尿病"),
])
def test_short_name_jp(code, ja):
    concept = _build_diagnosis_codeable_concept(code, "icd-10", "JP")
    assert concept["text"] == ja
    assert concept["text"] == lookup("condition-short-name", code, "ja")


def test_code_without_short_name_falls_back_to_primary_display():
    # M48 (spinal stenosis) has no short-name entry; text should fall back to
    # the primary display (i.e. equal coding[].display), not the raw code.
    concept = _build_diagnosis_codeable_concept("M48.9", "icd-10-cm", "US")
    assert concept["text"] == concept["coding"][0]["display"]
    assert concept["text"] != "M48"
