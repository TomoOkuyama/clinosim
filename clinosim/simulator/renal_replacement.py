"""Renal replacement therapy for AKI whose hyperkalemia or severe metabolic
acidosis persists (Issue #3830).

A session of intermittent hemodialysis is due on a hospital day when the day's
potassium or total CO2 meets the indication, the kidney function has not
recovered and the indication already held ``medical_response_days`` earlier (the
medical response comes first). A session sets the state's ``dialysis_clearance``
(``start_session``); the physiology derives the potassium, bicarbonate,
creatinine and urea from the effective renal function and acid-base balance,
and the effect wears off daily (``decay_dialysis_clearance``). Values live in
``reference_data/renal_replacement.yaml``. Everything here is RNG-free.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import OrderResult


class RenalReplacementRules(BaseModel):
    """Schema of ``reference_data/renal_replacement.yaml`` (Issue #3830)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    procedure_type: str = Field(min_length=1)
    potassium_lab: str = Field(min_length=1)
    total_co2_lab: str = Field(min_length=1)
    renal_function_below: float = Field(gt=0, le=1)
    medical_response_days: int = Field(ge=0)
    session_hour: int = Field(ge=0, le=23)
    clearance_per_session: float = Field(gt=0, le=1)
    daily_decay: float = Field(ge=0, lt=1)
    discharge_defer_days: int = Field(ge=0)
    negligible_clearance: float = Field(gt=0, lt=1)


@functools.cache
def renal_replacement_rules() -> RenalReplacementRules:
    """The validated renal replacement rules."""
    return RenalReplacementRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "renal_replacement.yaml")
    )


def indication_present(results: Iterable[OrderResult]) -> bool:
    """True when the results (a day's) show a potassium at or above the
    hyperkalemia treatment threshold or a total CO2 at or below the unresolved
    limit of the AKI gate."""
    from clinosim.modules.drug_safety.hyperkalemia import hyperkalemia_rules
    from clinosim.simulator.aki_response import aki_response_rules

    rules = renal_replacement_rules()
    potassium_limit = hyperkalemia_rules().treat_threshold_mmol_l
    co2_limit = aki_response_rules().unresolved_total_co2_mmol_l
    for r in results:
        if not isinstance(r.value, (int, float)):
            continue
        if r.lab_name == rules.potassium_lab and r.value >= potassium_limit:
            return True
        if r.lab_name == rules.total_co2_lab and r.value <= co2_limit:
            return True
    return False


def renal_replacement_due(
    day_results: Iterable[OrderResult],
    state: PhysiologicalState,
    *,
    day: int,
    first_indication_day: int | None,
) -> bool:
    """True when a session is due on ``day``: the day's results show the
    indication, the kidney function has not recovered, and the indication was
    first seen at least ``medical_response_days`` days ago."""
    rules = renal_replacement_rules()
    if first_indication_day is None or day - first_indication_day < rules.medical_response_days:
        return False
    if state.renal_function >= rules.renal_function_below:
        return False
    return indication_present(day_results)


def start_session(state: PhysiologicalState) -> None:
    """A session clears ``clearance_per_session`` of the kidney failure (never
    less than the effect still left from the last one)."""
    state.dialysis_clearance = max(state.dialysis_clearance, renal_replacement_rules().clearance_per_session)


def decay_dialysis_clearance(state: PhysiologicalState) -> None:
    """The effect of the last session wears off by ``daily_decay`` per day."""
    if state.dialysis_clearance > 0.0:
        rules = renal_replacement_rules()
        state.dialysis_clearance *= rules.daily_decay
        if state.dialysis_clearance < rules.negligible_clearance:
            state.dialysis_clearance = 0.0
