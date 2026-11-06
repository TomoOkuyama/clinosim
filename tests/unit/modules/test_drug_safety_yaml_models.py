"""The drug-safety reference YAML is validated by extra="forbid" Pydantic models."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.modules.drug_safety import _models as models

pytestmark = pytest.mark.unit

_REF = Path(__file__).resolve().parents[3] / "clinosim/modules/drug_safety/reference_data"
_FILES = {
    "contraindications": models.ContraindicationsFile,
    "disease_contraindications": models.DiseaseContraindicationsFile,
    "demographic_gates": models.DemographicGatesFile,
    "drug_substitution": models.DrugSubstitutionFile,
}


def _data(name: str) -> dict:
    data = yaml.safe_load((_REF / f"{name}.yaml").read_text(encoding="utf-8"))
    data.pop("metadata", None)
    return data


@pytest.mark.parametrize("name", sorted(_FILES))
def test_the_shipped_file_validates(name: str) -> None:
    _FILES[name].model_validate(_data(name))


def _bad(name: str, mutate) -> None:
    data = _data(name)
    mutate(data)
    with pytest.raises(ValueError):
        _FILES[name].model_validate(data)


def test_an_unknown_drug_class_fails() -> None:
    _bad("contraindications", lambda d: d["rules"][0].update(lhs="no.such.class"))


def test_a_duplicate_rule_id_fails() -> None:
    _bad("contraindications", lambda d: d["rules"].append(dict(d["rules"][0])))


def test_a_reconciliation_rule_must_name_a_rule() -> None:
    _bad("contraindications", lambda d: d["discharge_reconciliation_rules"].append("no_such_rule"))


def test_a_misspelled_key_fails() -> None:
    _bad("disease_contraindications", lambda d: d["rules"][0].update(severty="major"))


def test_a_demographic_rule_must_gate_age_or_sex() -> None:
    def strip(d: dict) -> None:
        d["rules"][0].pop("min_age", None)
        d["rules"][0].pop("sex", None)

    _bad("demographic_gates", strip)


def test_an_alternative_must_be_a_catalog_drug() -> None:
    _bad("drug_substitution", lambda d: next(iter(d["indications"].values()))["alternatives"][0].update(drug_id="x"))


def test_an_unknown_severity_fails() -> None:
    _bad("demographic_gates", lambda d: d["rules"][0].update(severity="severe"))
