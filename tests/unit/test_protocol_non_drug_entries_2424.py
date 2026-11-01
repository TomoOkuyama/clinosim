"""Protocol drug lists hold catalog drugs only; procedures and blood products
use their own keys and carry procedure codes (Issue #2424)."""

from __future__ import annotations

import glob
from pathlib import Path

import pytest
import yaml

import clinosim
from clinosim.codes.snomed import snomed_for_phrase
from clinosim.modules.disease.protocol import _NAME_ONLY_DRUG_EXEMPT, _validate_no_name_only_drug
from clinosim.modules.order.treatment_classifier import classify_escalation_treatment
from clinosim.types.encounter import OrderType

pytestmark = pytest.mark.unit

_DISEASES = Path(clinosim.__file__).parent / "modules/disease/reference_data"


def _name_only(node: object) -> list[str]:
    if isinstance(node, dict):
        found = [node["drug"]] if isinstance(node.get("drug"), str) and not node.get("drug_id") else []
        return found + [n for v in node.values() for n in _name_only(v)]
    if isinstance(node, list):
        return [n for v in node for n in _name_only(v)]
    return []


def test_no_name_only_drug_entry_outside_the_exemption() -> None:
    names = {n for f in glob.glob(str(_DISEASES / "*.yaml")) for n in _name_only(yaml.safe_load(open(f)))}
    assert names <= _NAME_ONLY_DRUG_EXEMPT, sorted(names - _NAME_ONLY_DRUG_EXEMPT)


def test_loader_rejects_a_name_only_drug() -> None:
    with pytest.raises(ValueError, match="without a drug_id"):
        _validate_no_name_only_drug("x", {"drugs": {"first_line": {"us": [{"drug": "Some drug", "dose": "1 mg"}]}}})
    _validate_no_name_only_drug("x", {"drugs": {"first_line": {"us": [{"drug_id": "heparin"}]}}})


@pytest.mark.parametrize(
    "display,code",
    [
        ("Intubation_and_mechanical_ventilation (TV 6mL/kg, PEEP 5)", "1258985005"),
        ("Packed_RBC_transfusion (transfuse to Hb 7)", "116863004"),
        ("Emergent_hemodialysis (stat)", "302497006"),
        ("NIV_BiPAP (IPAP 12 EPAP 5)", "47545007"),
        ("Vertebroplasty Percutaneous vertebroplasty under fluoroscopy", "401226007"),
        ("Kyphoplasty Balloon kyphoplasty under fluoroscopy", "431995006"),
        ("Catheter-directed thrombolysis Alteplase 0.5-1mg/h via catheter x12-24h", "233428003"),
    ],
)
def test_remodelled_procedures_are_coded(display: str, code: str) -> None:
    assert snomed_for_phrase(display) == code


def test_escalation_procedure_key_classifies_as_procedure() -> None:
    assert classify_escalation_treatment({"procedure": "Hemodialysis"}) == OrderType.PROCEDURE
