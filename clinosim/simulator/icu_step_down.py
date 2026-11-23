"""When an ICU stay ends (Issue #3555).

The daily loop records, for every hospital day, whether the patient had
ICU-level support (``day_has_icu_support``); after the loop the step-down day
is derived from that record (``step_down_day``). Values and the rules'
description live in ``reference_data/icu_step_down.yaml``. Everything here is
RNG-free.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml

StepDownBasis = Literal["", "criteria", "before_discharge"]


class IcuStepDownRules(BaseModel):
    """Schema of ``reference_data/icu_step_down.yaml`` (Issue #3555)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_icu_days: int = Field(ge=1)
    ward_consciousness_levels: tuple[str, ...] = Field(min_length=1)
    icu_min_oxygen_flow_lpm: float = Field(gt=0)


@functools.cache
def icu_step_down_rules() -> IcuStepDownRules:
    """The validated step-down rules."""
    return IcuStepDownRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "icu_step_down.yaml")
    )


def day_has_icu_support(
    *,
    physiology_needs_icu: bool,
    ventilated: bool,
    vasoactive_infusion: bool,
    consciousness_levels: Iterable[str],
    oxygen_flows_lpm: Iterable[float],
    icu_complication: bool,
) -> bool:
    """Whether one hospital day had ICU-level support (see the YAML header)."""
    rules = icu_step_down_rules()
    if physiology_needs_icu or ventilated or vasoactive_infusion or icu_complication:
        return True
    if any(level and level not in rules.ward_consciousness_levels for level in consciousness_levels):
        return True
    return any(flow >= rules.icu_min_oxygen_flow_lpm for flow in oxygen_flows_lpm)


def step_down_day(
    transfer_day: int, support: Sequence[bool], actual_los: int, *, died: bool
) -> tuple[int | None, StepDownBasis]:
    """``(step-down day, basis)`` of a stay transferred to the ICU on
    ``transfer_day``: ``support[i]`` is whether hospital day ``i`` had ICU-level
    support, ``actual_los`` the number of hospital days (the discharge day is
    ``actual_los - 1``). The basis is ``"criteria"`` (the first day after which
    no support is recorded), ``"before_discharge"`` (the day before the
    discharge day, the criteria never being met earlier) or ``""`` (no
    step-down: no transfer, a death, or too short a stay)."""
    if died or transfer_day < 0:
        return None, ""
    last = actual_los - 2
    first = transfer_day + icu_step_down_rules().min_icu_days
    if first > last:
        return None, ""
    for day in range(first, last + 1):
        if not any(support[day:actual_los]):
            return day, "criteria"
    return last, "before_discharge"
