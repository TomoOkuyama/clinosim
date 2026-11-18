"""Physiological coupling of the daily intake / output record (Issue #3271).

Pure functions: the means the daily sampler draws around (the draws themselves
stay in ``clinosim.simulator.vitals_pipeline._generate_daily_io``, in their
original order, so the stay RNG is unchanged) and the volume-status feedback of
the day's net balance. Parameters are in ``reference_data/fluid_balance.yaml``;
see that file for sources and for which values are modelling choices.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from clinosim.datafiles import load_validated_yaml

__all__ = [
    "FluidContext",
    "fluid_params",
    "insensible_loss_ml",
    "intake_is_restricted",
    "iv_regimen",
    "oral_cap_ml",
    "urine_mean_ml",
    "volume_status_shift",
    "weight_scale",
]

_PATH = Path(__file__).resolve().parent / "reference_data" / "fluid_balance.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Kidney(_Strict):
    renal_failing_below: float
    renal_regulating_above: float
    oliguria_ml_per_kg_per_h: float
    failing_urine_fraction_of_oliguria: float
    excretion_capacity_ml_per_unit_renal: float
    volume_gain: float
    volume_factor_min: float
    volume_factor_max: float
    perfusion_oliguria_below: float
    perfusion_factor_min: float


class _Loop(_Strict):
    drug_classes: list[str]
    net_negative_target_ml: float
    full_effect_volume_status: float
    minimum_fraction_at_euvolemia: float


class _Intake(_Strict):
    resuscitation_diseases: list[str]
    restricted_diseases: list[str]
    restrict_if_volume_status_at_or_above: float
    restrict_if_cardiac_function_below: float
    restrict_if_renal_function_below: float
    kvo_iv_ml: float
    kvo_iv_sd: float
    restricted_oral_ml: float
    early_day_iv_ml: float
    early_day_iv_sd: float


class _Feedback(_Strict):
    ml_per_unit_volume_status: float


class _FluidBalanceFile(_Strict):
    reference_weight_kg: float
    weight_scale_min: float
    weight_scale_max: float
    insensible_ml_per_day_at_reference: float
    kidney: _Kidney
    loop_diuretic: _Loop
    intake: _Intake
    volume_feedback: _Feedback


@lru_cache(maxsize=1)
def fluid_params() -> _FluidBalanceFile:
    """The validated ``fluid_balance.yaml``."""
    return _FluidBalanceFile.model_validate(load_validated_yaml(_PATH, _FluidBalanceFile))


@dataclass(frozen=True)
class FluidContext:
    """What the day's fluid balance depends on besides the physiological state."""

    disease_id: str = ""
    weight_kg: float = 70.0
    on_loop_diuretic: bool = False


def weight_scale(weight_kg: float) -> float:
    """Volume scale relative to the reference adult, bounded."""
    p = fluid_params()
    return max(p.weight_scale_min, min(p.weight_scale_max, weight_kg / p.reference_weight_kg))


def insensible_loss_ml(weight_kg: float) -> float:
    """Daily insensible loss (skin + respiratory) for a patient of ``weight_kg``."""
    return fluid_params().insensible_ml_per_day_at_reference * weight_scale(weight_kg)


def intake_is_restricted(state: Any, ctx: FluidContext) -> bool:
    """Fluid-restricted management: a disease or a physiological state in which
    extra volume is not given (heart failure, overload, failing kidney); a
    volume-depleted patient is never restricted outside such a disease."""
    k = fluid_params().intake
    if ctx.disease_id in k.restricted_diseases:
        return True
    if state.volume_status < 0.0:
        return False  # depleted: volume is replaced whatever the organ function
    return (
        state.volume_status >= k.restrict_if_volume_status_at_or_above
        or state.cardiac_function < k.restrict_if_cardiac_function_below
        or state.renal_function < k.restrict_if_renal_function_below
    )


def iv_regimen(state: Any, ctx: FluidContext, day: int, early_day_max: int) -> str:
    """Which IV regimen applies today: ``restricted`` | ``resuscitation`` |
    ``early`` | ``routine`` (the day-threshold / dehydration branches then
    apply in the sampler for ``resuscitation`` and ``routine``)."""
    if intake_is_restricted(state, ctx):
        return "restricted"
    if ctx.disease_id in fluid_params().intake.resuscitation_diseases:
        return "resuscitation"
    if day <= early_day_max:
        return "early"
    return "routine"


def oral_cap_ml(state: Any, ctx: FluidContext) -> float | None:
    """Upper bound of the day's oral intake mean under fluid restriction."""
    if intake_is_restricted(state, ctx):
        return fluid_params().intake.restricted_oral_ml * weight_scale(ctx.weight_kg)
    return None


def _regulation(renal_function: float) -> float:
    k = fluid_params().kidney
    span = k.renal_regulating_above - k.renal_failing_below
    return max(0.0, min(1.0, (renal_function - k.renal_failing_below) / span))


def urine_mean_ml(
    state: Any,
    ctx: FluidContext,
    intake_ml: float,
    other_loss_ml: float,
    base_urine_ml: float,
) -> float:
    """Expected urine output of the day.

    A regulating kidney excretes the intake not lost otherwise, up to its
    capacity, more when volume overloaded and less when depleted or in shock;
    a failing kidney makes a fixed oliguric volume (KDIGO 0.5 mL/kg/h
    criterion); a loop diuretic drives a responding patient to a net-negative
    balance. ``base_urine_ml`` is the renal-function-proportional baseline.
    """
    p = fluid_params()
    k = p.kidney
    reg = _regulation(state.renal_function)
    capacity = k.excretion_capacity_ml_per_unit_renal * state.renal_function * weight_scale(ctx.weight_kg)
    target = min(max(intake_ml - other_loss_ml, 0.0), capacity)
    # Not-regulating floor: the oliguric volume, and never above the baseline.
    oliguric = min(
        base_urine_ml,
        k.failing_urine_fraction_of_oliguria * k.oliguria_ml_per_kg_per_h * 24.0 * ctx.weight_kg,
    )
    urine = reg * target + (1.0 - reg) * oliguric
    vol_factor = 1.0 + k.volume_gain * state.volume_status
    urine *= max(k.volume_factor_min, min(k.volume_factor_max, vol_factor))
    if state.perfusion_status < k.perfusion_oliguria_below:
        frac = state.perfusion_status / k.perfusion_oliguria_below
        urine *= max(k.perfusion_factor_min, frac)
    if ctx.on_loop_diuretic:
        loop = p.loop_diuretic
        floor = loop.minimum_fraction_at_euvolemia
        frac = floor + (1.0 - floor) * state.volume_status / loop.full_effect_volume_status
        frac = max(0.0, min(1.0, frac))
        diuresis_target = intake_ml - other_loss_ml + loop.net_negative_target_ml * frac * weight_scale(ctx.weight_kg)
        urine = max(urine, reg * diuresis_target)
    return urine


def volume_status_shift(net_balance_ml: float, weight_kg: float) -> float:
    """Change in ``volume_status`` produced by a day's net balance (positive
    balance raises it, negative lowers it)."""
    p = fluid_params()
    return net_balance_ml / (p.volume_feedback.ml_per_unit_volume_status * weight_scale(weight_kg))
