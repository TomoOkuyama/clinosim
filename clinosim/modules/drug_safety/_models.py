"""Pydantic models of the drug-safety reference YAML (configuration spec:
module reference YAML is validated at load by an ``extra="forbid"`` model).

Cross-references are checked at load: drug classes and drug ids exist in the
drug catalog, rule ids are unique, and the reconciliation list names rules.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

# The severities a rule may assert ("allowed" is the verdict of no rule).
_RuleSeverity = Literal["minor", "moderate", "major", "contraindicated"]


def _catalog_classes() -> set[str]:
    from clinosim.codes.drugs import all_drug_ids, drug_classes

    return {c for d in all_drug_ids() for c in drug_classes(d)}


def _check_class(name: str) -> str:
    if name not in _catalog_classes():
        raise ValueError(f"drug class {name!r} is not a class of any catalog drug")
    return name


def _unique_ids(rules: list) -> list:
    ids = [r.id for r in rules]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f"duplicate rule ids: {dup}")
    return rules


class _Rationale(BaseModel):
    model_config = ConfigDict(extra="forbid")
    en: str = Field(min_length=1)
    ja: str = Field(min_length=1)


class _InteractionRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    lhs: str
    rhs: str
    severity: _RuleSeverity
    rationale: _Rationale
    source: str = Field(min_length=1)
    substitution_hint: str | None = None

    _classes = field_validator("lhs", "rhs")(classmethod(lambda cls, v: _check_class(v)))


class _TripleTherapyPlan(BaseModel):
    """Antithrombotic plan when a patient on an anticoagulant leaves on DAPT after ACS."""

    model_config = ConfigDict(extra="forbid")
    aspirin_days: StrictInt = Field(ge=1)
    p2y12_with_oac: str
    p2y12_dose: str = Field(min_length=1)

    @field_validator("p2y12_with_oac")
    @classmethod
    def _catalog_drug(cls, v: str) -> str:
        from clinosim.codes.drugs import get_drug

        if get_drug(v) is None:
            raise ValueError(f"p2y12_with_oac {v!r} is not in the drug catalog")
        return v


class ContraindicationsFile(BaseModel):
    """Shape of ``contraindications.yaml``."""

    model_config = ConfigDict(extra="forbid")
    rules: list[_InteractionRule] = Field(min_length=1)
    discharge_reconciliation_rules: list[str] = []
    triple_therapy_after_acs: _TripleTherapyPlan

    _ids = field_validator("rules")(classmethod(lambda cls, v: _unique_ids(v)))

    @model_validator(mode="after")
    def _reconciliation_names_rules(self) -> ContraindicationsFile:
        unknown = sorted(set(self.discharge_reconciliation_rules) - {r.id for r in self.rules})
        if unknown:
            raise ValueError(f"discharge_reconciliation_rules names no rule: {unknown}")
        return self


class _DiseasePredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    icd_prefix: list[str] = Field(min_length=1)
    stage_in: list[str] = []


class _DiseaseRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    disease_predicate: _DiseasePredicate
    drug_class: str
    severity: _RuleSeverity
    rationale: _Rationale
    source: str = Field(min_length=1)
    substitution_hint: str | None = None

    _class = field_validator("drug_class")(classmethod(lambda cls, v: _check_class(v)))


class DiseaseContraindicationsFile(BaseModel):
    """Shape of ``disease_contraindications.yaml``."""

    model_config = ConfigDict(extra="forbid")
    rules: list[_DiseaseRule] = Field(min_length=1)

    _ids = field_validator("rules")(classmethod(lambda cls, v: _unique_ids(v)))


class _DemographicRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    drug_names: list[str] = Field(min_length=1)
    severity: _RuleSeverity
    rationale: _Rationale
    references: str = Field(min_length=1)
    min_age: StrictInt | None = Field(default=None, ge=0)
    sex: Literal["male", "female"] | None = None
    exception_indications: list[str] = []

    @model_validator(mode="after")
    def _gates_something(self) -> _DemographicRule:
        if self.min_age is None and self.sex is None:
            raise ValueError(f"demographic rule {self.id!r} gates neither age nor sex")
        return self


class DemographicGatesFile(BaseModel):
    """Shape of ``demographic_gates.yaml``."""

    model_config = ConfigDict(extra="forbid")
    rules: list[_DemographicRule] = Field(min_length=1)

    _ids = field_validator("rules")(classmethod(lambda cls, v: _unique_ids(v)))


class _Alternative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drug_id: str
    default_dose: str = Field(min_length=1)
    default_frequency: str = Field(min_length=1)
    default_route: str = Field(min_length=1)

    @field_validator("drug_id")
    @classmethod
    def _catalog_drug(cls, v: str) -> str:
        from clinosim.codes.drugs import get_drug

        if get_drug(v) is None:
            raise ValueError(f"drug_id {v!r} is not in the drug catalog")
        return v


class _Indication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1)
    alternatives: list[_Alternative] = Field(min_length=1)


class DrugSubstitutionFile(BaseModel):
    """Shape of ``drug_substitution.yaml``."""

    model_config = ConfigDict(extra="forbid")
    indications: dict[str, _Indication] = Field(min_length=1)
