"""JP protocol drug orders take their code from the drug catalog (Issue #2351).

Disease YAMLs no longer carry ``code_yj``. A JP order's ``order_code`` is the
catalog YJ product for the drug and route — the code the FHIR medication
builders emit — so CIF and FHIR agree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.codes.drugs import jp_drug_code_for_name
from clinosim.modules.order.engine import protocol_drug_order_code
from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


def test_no_disease_yaml_carries_code_yj() -> None:
    offenders = [
        p.name
        for p in (_ROOT / "clinosim/modules/disease/reference_data").glob("*.yaml")
        if "code_yj:" in p.read_text()
    ]
    assert not offenders


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ({"drug": "Furosemide", "dose": "20mg IV", "route": "IV"}, "2139401A2137"),
        ({"drug": "Furosemide", "dose": "40mg PO daily"}, "2139005F1052"),
        ({"drug": "Unfractionated Heparin", "dose": "5000U IV", "route": "IV"}, jp_drug_code_for_name("Heparin", "IV")),
        ({"drug": "Norepinephrine", "dose": "0.05ug/kg/min IV drip"}, ""),
    ],
)
def test_jp_order_code_is_the_catalog_product_for_the_route(spec: dict, expected: str) -> None:
    assert protocol_drug_order_code(spec, "japan") == (expected or "")


def test_us_order_code_is_the_rxnorm_field() -> None:
    assert protocol_drug_order_code({"drug": "Furosemide", "code_rxnorm": "4603"}, "us") == "4603"


@pytest.mark.parametrize("name", ["Furosemide 20mg", "Unfractionated Heparin", "Normal_saline", "Alteplase (tPA)"])
def test_order_code_matches_the_fhir_coding(name: str) -> None:
    concept, _ = _resolve_medication_concept(name, order_code="", country="JP", route="IV")
    assert concept["coding"][0]["code"] == (jp_drug_code_for_name(name, "IV") or "NOCODED")
