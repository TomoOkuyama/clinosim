"""_fhir_encounter.py's encounter-type SNOMED display must resolve via
codes/data/snomed-ct.yaml + code_lookup, keyed by the SNOMED code itself —
not the internal encounter-type enum via a hardcoded _ENCOUNTER_TYPE_SNOMED_JA
dict (2026-07-02 grand design review, display-dict migration).
"""

import pytest

from clinosim.codes import lookup
from clinosim.modules.output._fhir_encounter import _build_encounter

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("enc_type,code,en", [
    ("inpatient", "32485007", "Hospital admission"),
    ("emergency", "50849002", "Emergency hospital admission"),
    ("outpatient", "270427003", "Patient-initiated encounter"),
    ("icu", "183452005", "Emergency hospital admission"),
])
def test_encounter_type_display_us(enc_type, code, en):
    resource = _build_encounter({"encounter_id": "E1", "encounter_type": enc_type}, "P1", country="US")
    coding = resource["type"][0]["coding"][0]
    assert coding["code"] == code
    assert coding["display"] == en == lookup("snomed-ct", code, "en")


@pytest.mark.parametrize("enc_type,code,ja", [
    ("inpatient", "32485007", "入院"),
    ("emergency", "50849002", "救急入院"),
    ("outpatient", "270427003", "外来受診"),
    ("icu", "183452005", "救急入院"),
])
def test_encounter_type_display_jp(enc_type, code, ja):
    resource = _build_encounter({"encounter_id": "E1", "encounter_type": enc_type}, "P1", country="JP")
    coding = resource["type"][0]["coding"][0]
    assert coding["code"] == code
    assert coding["display"] == ja == lookup("snomed-ct", code, "ja")
