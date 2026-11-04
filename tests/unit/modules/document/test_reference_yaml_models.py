"""The document reference YAML models reject every malformed shape (Issue #2572)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel

from clinosim.datafiles import load_data_yaml
from clinosim.modules.document import reference_data_loaders as rdl
from clinosim.reference_data import load_reference_yaml

pytestmark = pytest.mark.unit

_Break = Callable[[dict[str, Any]], Any]

_SHIPPED: dict[type[BaseModel], Callable[[], dict[str, Any]]] = {
    rdl.PhysicalExamFindings: lambda: load_data_yaml(rdl._REF_DIR / "physical_exam_findings.yaml"),
    rdl.DischargeInstructions: lambda: load_reference_yaml(rdl._REF_DIR / "clinosim-discharge-instruction.yaml"),
    rdl.ChiefComplaintVariants: lambda: load_data_yaml(rdl._NARRATIVE_REF_DIR / "chief_complaint_variants.yaml"),
    rdl.BedsideProcedureCodes: lambda: load_data_yaml(rdl._REF_DIR / "bedside_procedure_codes.yaml"),
    rdl.NursingContent: lambda: load_reference_yaml(rdl._REF_DIR / "clinosim-nursing-content.yaml"),
}


def _first(mapping: dict[str, Any]) -> Any:
    return next(iter(mapping.values()))


@pytest.mark.parametrize("model", list(_SHIPPED))
def test_shipped_yaml_is_accepted(model: type[BaseModel]) -> None:
    model.model_validate(_SHIPPED[model]())


@pytest.mark.parametrize(
    ("model", "break_it", "message"),
    [
        (rdl.PhysicalExamFindings, lambda d: d.pop("findings"), "findings"),
        (rdl.PhysicalExamFindings, lambda d: d["baseline"]["uncomplicated_improvement"].pop("day_0"), "day_0"),
        (rdl.DischargeInstructions, lambda d: d.pop("disease_specific"), "disease_specific"),
        (rdl.DischargeInstructions, lambda d: d["baseline"].update({"hydrate": {}}), "hydrate"),
        (rdl.DischargeInstructions, lambda d: _first(d["disease_specific"]).update({"x": "text"}), "x"),
        (rdl.DischargeInstructions, lambda d: d["disease_specific"].update({"y": ["a"]}), "y"),
        (rdl.ChiefComplaintVariants, lambda d: d.clear(), "empty top-level"),
        (rdl.ChiefComplaintVariants, lambda d: d.pop("variants"), "variants"),
        (rdl.ChiefComplaintVariants, lambda d: d.update({"variants": {}}), "variants"),
        (rdl.ChiefComplaintVariants, lambda d: d["variants"].update({"x": []}), "at least 1 item"),
        (rdl.ChiefComplaintVariants, lambda d: d["variants"].update({"x": ["  "]}), "non-empty string"),
        (rdl.ChiefComplaintVariants, lambda d: d["variants"].update({"x": [3]}), "valid string"),
        (rdl.BedsideProcedureCodes, lambda d: d.clear(), "empty top-level"),
        (rdl.BedsideProcedureCodes, lambda d: d.pop("operative_note_codes"), "operative_note_codes"),
        (rdl.BedsideProcedureCodes, lambda d: d.update({"procedure_note_codes": []}), "at least 1 item"),
        (rdl.BedsideProcedureCodes, lambda d: d["operative_note_codes"].append(""), "non-empty string"),
        (
            rdl.BedsideProcedureCodes,
            lambda d: d["operative_note_codes"].append(d["procedure_note_codes"][0]),
            "both buckets",
        ),
        (rdl.NursingContent, lambda d: d.update({"chronic_icd10": {}}), "empty or not a mapping"),
        (rdl.NursingContent, lambda d: _first(d["acute_disease"]).pop("care_plan"), "care_plan"),
        (rdl.NursingContent, lambda d: _first(d["acute_disease"])["care_plan"]["ja"].append(" "), "non-empty string"),
    ],
)
def test_rejections(model: type[BaseModel], break_it: _Break, message: str) -> None:
    data = copy.deepcopy(_SHIPPED[model]())
    break_it(data)
    with pytest.raises(ValueError, match=message):
        model.model_validate(data)
