"""Every simulator reference YAML is validated by a model that rejects unknown
keys, nested ones included (Issue #2956)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from clinosim.datafiles import load_data_yaml, load_validated_yaml
from clinosim.simulator.adl_ceiling import AdlCeilingRules
from clinosim.simulator.aki_response import AkiResponseRules
from clinosim.simulator.device_removal import DeviceRemovalRules
from clinosim.simulator.diagnosis_rules import DiagnosisRulesFile
from clinosim.simulator.helpers import ChronicPropagationRules
from clinosim.simulator.implied_chronic import ImpliedChronicPrevalence
from clinosim.simulator.ketoacidosis_resolution import KetoacidosisResolutionRules
from clinosim.simulator.maintenance_iv_fluid import MaintenanceIVFluidRules
from clinosim.simulator.medication_pipeline import RenalMedicationRules, VasoactiveHoldRules
from clinosim.simulator.mixed_condition import MixedConditionRules
from clinosim.simulator.sex_gating import SexRestrictionRules
from clinosim.simulator.statin_monitoring import StatinMonitoringRules
from clinosim.simulator.vasoactive_support import VasoactiveWeaningRules
from clinosim.simulator.vasopressor_initiation import VasopressorInitiationRules

pytestmark = pytest.mark.unit

_DIR = Path(__file__).resolve().parents[3] / "clinosim" / "simulator" / "reference_data"

_MODELS: dict[str, type[BaseModel]] = {
    "adl_functional_ceilings.yaml": AdlCeilingRules,
    "chronic_propagation.yaml": ChronicPropagationRules,
    "device_removal.yaml": DeviceRemovalRules,
    "diagnosis_rules.yaml": DiagnosisRulesFile,
    "icd10_sex_restrictions.yaml": SexRestrictionRules,
    "implied_chronic_prevalence.yaml": ImpliedChronicPrevalence,
    "aki_response.yaml": AkiResponseRules,
    "ketoacidosis_resolution.yaml": KetoacidosisResolutionRules,
    "maintenance_iv_fluid.yaml": MaintenanceIVFluidRules,
    "mixed_condition.yaml": MixedConditionRules,
    "renal_medication_rules.yaml": RenalMedicationRules,
    "statin_monitoring.yaml": StatinMonitoringRules,
    "vasoactive_hold.yaml": VasoactiveHoldRules,
    "vasoactive_weaning.yaml": VasoactiveWeaningRules,
    "vasopressor_initiation.yaml": VasopressorInitiationRules,
}


def _rename(d: dict[str, Any], old: str, new: str) -> None:
    d[new] = d.pop(old)


def test_every_simulator_reference_yaml_has_a_model() -> None:
    assert sorted(p.name for p in _DIR.glob("*.yaml")) == sorted(_MODELS)


@pytest.mark.parametrize("name", sorted(_MODELS))
def test_shipped_file_validates(name: str) -> None:
    assert load_validated_yaml(_DIR / name, _MODELS[name]) == load_data_yaml(_DIR / name)


@pytest.mark.parametrize("name", sorted(_MODELS))
def test_misspelled_top_level_key_raises(name: str) -> None:
    data = copy.deepcopy(load_data_yaml(_DIR / name))
    first = next(iter(data))
    _rename(data, first, first + "s")
    with pytest.raises(ValidationError):
        _MODELS[name].model_validate(data)


def _stray_top_level_key(data: dict[str, Any]) -> None:
    data["extra_section"] = {}


# A misspelled (or misshapen) entry below the top level. Files whose sections
# are plain lists or maps of scalars get a malformed nested value instead.
_NESTED: dict[str, Callable[[dict[str, Any]], None]] = {
    "adl_functional_ceilings.yaml": lambda d: d["conditions"][0].update(stage_atribute="x"),
    "chronic_propagation.yaml": lambda d: d["chronic_propagatable"].append("E11.9"),
    "device_removal.yaml": lambda d: _rename(
        d["kinds"]["cvc"]["indications"]["hemodynamic_monitoring"], "anchor", "ancor"
    ),
    "diagnosis_rules.yaml": lambda d: _rename(d["unknown_condition_codes"]["default"], "admission", "admision"),
    "icd10_sex_restrictions.yaml": lambda d: d["male_only"].append({"code": "N40"}),
    "implied_chronic_prevalence.yaml": lambda d: d["prevalence"]["cerebral_infarction"].update(I48=1.5),
    "aki_response.yaml": lambda d: d.update(fever_celsius="hot"),
    "ketoacidosis_resolution.yaml": lambda d: d.update(ph_min="acidic"),
    "maintenance_iv_fluid.yaml": lambda d: d.update(grace_days={"days": 1}),
    "mixed_condition.yaml": lambda d: d.update(recovery_days={"days": 1}),
    "renal_medication_rules.yaml": lambda d: d["renal_drugs"].update(metformin="hld"),
    "statin_monitoring.yaml": lambda d: _rename(d["countries"]["US"]["step_up_ldl"][0], "ldl_mg_dl", "ldl_mgdl"),
    "vasoactive_hold.yaml": lambda d: d["held_classes"].append("antihypertensives"),
    "vasoactive_weaning.yaml": lambda d: d.update(stable_hours={"hours": 24}),
    "vasopressor_initiation.yaml": lambda d: d["fluid_drug_ids"].append({"drug": "normal_saline"}),
}


@pytest.mark.parametrize("name", sorted(_MODELS))
def test_misspelled_nested_key_raises(name: str) -> None:
    data = copy.deepcopy(load_data_yaml(_DIR / name))
    _NESTED[name](data)
    with pytest.raises(ValidationError):
        _MODELS[name].model_validate(data)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: _rename(d["visit_purpose_codes"], "fallback", "fallbak"),
        lambda d: d["visit_purpose_codes"]["by_visit_type"]["pediatric_visit"].update(by_vist={}),
        lambda d: _rename(d["differential_findings"]["labs"]["CRP"], "above", "abov"),
        lambda d: d["differential_findings"].update(day2_imaging={}),
        lambda d: d["unknown_condition_codes"]["by_pattern"]["fever_unknown"].update(resolved="R50.9"),
    ],
)
def test_diagnosis_rules_nested_typos_raise(mutate: Callable[[dict[str, Any]], None]) -> None:
    data = copy.deepcopy(load_data_yaml(_DIR / "diagnosis_rules.yaml"))
    mutate(data)
    with pytest.raises(ValidationError):
        DiagnosisRulesFile.model_validate(data)


def test_sex_restrictions_reject_a_code_locked_to_both_sexes() -> None:
    data = copy.deepcopy(load_data_yaml(_DIR / "icd10_sex_restrictions.yaml"))
    data["female_only"].append(data["male_only"][0])
    with pytest.raises(ValidationError, match="locked to both sexes"):
        SexRestrictionRules.model_validate(data)


@pytest.mark.parametrize("name", sorted(_MODELS))
def test_stray_top_level_section_raises(name: str) -> None:
    data = copy.deepcopy(load_data_yaml(_DIR / name))
    _stray_top_level_key(data)
    with pytest.raises(ValidationError):
        _MODELS[name].model_validate(data)
