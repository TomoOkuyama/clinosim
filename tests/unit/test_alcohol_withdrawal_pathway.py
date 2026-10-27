"""Alcohol withdrawal admission pathway (Issue #2049)."""

from __future__ import annotations

import pytest
import yaml

from clinosim.modules.disease.protocol import load_disease_protocol

pytestmark = pytest.mark.unit


def test_protocol_is_ed_admission_to_internal_medicine() -> None:
    proto = load_disease_protocol("alcohol_withdrawal")
    assert proto.admission_route == "emergency"
    assert proto.department == "internal_medicine"
    assert proto.icd_codes["primary"] == "F10.239"


def test_us_drugs_resolve_to_rxnorm() -> None:
    proto = load_disease_protocol("alcohol_withdrawal")
    with open("clinosim/locale/us/code_mapping_drug.yaml", encoding="utf-8") as fh:
        mapping = yaml.safe_load(fh)
    names = {d["drug"] for block in ("first_line", "discharge_oral") for d in proto.drugs[block]["us"]}
    assert names == {"Lorazepam", "Thiamine", "Folic acid"}
    assert all(mapping.get(n) for n in names)
