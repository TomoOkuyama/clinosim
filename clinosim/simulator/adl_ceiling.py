"""Premorbid Barthel Index ceiling from staged chronic functional conditions
(Issue #3237).

A patient whose chronic condition carries a stage listed in
``reference_data/adl_functional_ceilings.yaml`` (dementia by CDR stage) cannot
score above that stage's Barthel item ceilings, however far the acute illness
recovers. ``barthel_item_caps`` returns the per-item ceiling (the full Barthel
item maximum when no staged condition applies); the total ceiling is its sum.
Pure lookup, no RNG.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clinosim.datafiles import load_data_yaml
from clinosim.simulator._adl_thresholds import (
    ADL_COMP_BATHING_MAX,
    ADL_COMP_BLADDER_MAX,
    ADL_COMP_BOWEL_MAX,
    ADL_COMP_DRESSING_MAX,
    ADL_COMP_FEEDING_MAX,
    ADL_COMP_GROOMING_MAX,
    ADL_COMP_MOBILITY_MAX,
    ADL_COMP_STAIRS_MAX,
    ADL_COMP_TOILET_MAX,
    ADL_COMP_TRANSFERS_MAX,
)
from clinosim.types.patient import PatientProfile

_YAML = Path(__file__).resolve().parent / "reference_data" / "adl_functional_ceilings.yaml"

BARTHEL_ITEM_MAX: Mapping[str, int] = MappingProxyType(
    {
        "feeding": ADL_COMP_FEEDING_MAX,
        "bathing": ADL_COMP_BATHING_MAX,
        "grooming": ADL_COMP_GROOMING_MAX,
        "dressing": ADL_COMP_DRESSING_MAX,
        "bowel_control": ADL_COMP_BOWEL_MAX,
        "bladder_control": ADL_COMP_BLADDER_MAX,
        "toilet_use": ADL_COMP_TOILET_MAX,
        "transfers": ADL_COMP_TRANSFERS_MAX,
        "mobility": ADL_COMP_MOBILITY_MAX,
        "stairs": ADL_COMP_STAIRS_MAX,
    }
)
"""The ten Barthel items (``ADLAssessment`` field names) and their maxima."""

_BARTHEL_STEP = 5


class _ConditionCeiling(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_attribute: str = Field(min_length=1)
    item_caps_by_stage: dict[str, dict[str, int]] = Field(min_length=1)

    @field_validator("item_caps_by_stage")
    @classmethod
    def _items_on_the_barthel_scale(cls, v: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
        for stage, caps in v.items():
            for item, cap in caps.items():
                if item not in BARTHEL_ITEM_MAX:
                    raise ValueError(f"{stage!r}: {item!r} is not a Barthel item")
                if not 0 <= cap <= BARTHEL_ITEM_MAX[item] or cap % _BARTHEL_STEP:
                    raise ValueError(f"{stage!r}: {item} ceiling {cap} is not a level of the item")
        return v

    @model_validator(mode="after")
    def _stages_of_a_markov_attribute(self) -> _ConditionCeiling:
        from clinosim.modules.longitudinal.loader import load_attribute_specs
        from clinosim.modules.longitudinal.patterns.markov import MarkovSpec

        spec = load_attribute_specs().get(self.stage_attribute)
        if spec is None or not isinstance(spec.body, MarkovSpec):
            raise ValueError(f"{self.stage_attribute!r} is not a Markov stage attribute")
        unknown = sorted(set(self.item_caps_by_stage) - set(spec.body.states))
        if unknown:
            raise ValueError(f"{self.stage_attribute}: stages {unknown} are not states of the attribute")
        return self

    @property
    def icd_base(self) -> str:
        from clinosim.modules.longitudinal.loader import load_attribute_specs

        return str(load_attribute_specs()[self.stage_attribute].body.icd_base)  # type: ignore[union-attr]


class AdlCeilingRules(BaseModel):
    """Schema of ``reference_data/adl_functional_ceilings.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    conditions: tuple[_ConditionCeiling, ...] = Field(min_length=1)


@functools.lru_cache(maxsize=1)
def adl_ceiling_rules() -> AdlCeilingRules:
    """The validated premorbid ADL ceiling rules."""
    return AdlCeilingRules.model_validate(load_data_yaml(_YAML))


def barthel_item_caps(patient: PatientProfile) -> dict[str, int]:
    """Per-item Barthel ceiling for ``patient``: the lowest ceiling of every
    staged chronic condition listed in the rules, else the item maximum."""
    caps = dict(BARTHEL_ITEM_MAX)
    for rule in adl_ceiling_rules().conditions:
        base = rule.icd_base
        for cc in patient.chronic_conditions:
            if not cc.code.startswith(base):
                continue
            for item, cap in rule.item_caps_by_stage.get(cc.stage, {}).items():
                caps[item] = min(caps[item], cap)
    return caps
