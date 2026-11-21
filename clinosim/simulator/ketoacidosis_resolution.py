"""Ending the intravenous treatment of diabetic ketoacidosis (Issue #3450).

At the start of a hospital day, once the resulted labs meet the resolution
criteria of ``reference_data/ketoacidosis_resolution.yaml`` (or the insulin
infusion reached its day cap), the stay switches to subcutaneous basal insulin
(``ketoacidosis_transition_order``) and the running insulin infusion, saline and
potassium orders end ``overlap_hours`` later (``stop_ketoacidosis_infusions``):
status STOPPED and ``end_datetime`` set, so the MAR gives no dose of them from
then on. Everything here is RNG-free.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType


class KetoacidosisResolutionRules(BaseModel):
    """Schema of ``reference_data/ketoacidosis_resolution.yaml`` (Issue #3450)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disease_ids: tuple[str, ...] = Field(min_length=1)
    ph_lab: str = Field(min_length=1)
    ph_min: float = Field(gt=0)
    bicarbonate_lab: str = Field(min_length=1)
    bicarbonate_min: float = Field(gt=0)
    ketone_lab: str = Field(min_length=1)
    ketone_max_mmol_l: float = Field(gt=0)
    overlap_hours: float = Field(ge=0)
    max_infusion_days: int = Field(ge=1)
    regimen_block: str = Field(min_length=1)
    basal_drug_id: str = Field(min_length=1)
    infusion_insulin_drug_id: str = Field(min_length=1)
    stop_drug_ids: tuple[str, ...] = Field(min_length=1)
    stop_routes: tuple[str, ...] = Field(min_length=1)


@functools.cache
def ketoacidosis_resolution_rules() -> KetoacidosisResolutionRules:
    """The validated ketoacidosis-resolution rules."""
    return KetoacidosisResolutionRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "ketoacidosis_resolution.yaml")
    )


def _is_infusion_order(order: Order) -> bool:
    rules = ketoacidosis_resolution_rules()
    return (
        order.order_type == OrderType.MEDICATION
        and order.status == OrderStatus.PLACED
        and not order.single_dose
        and not (order.display_name or "").startswith("DISCONTINUE:")
        and order.drug_id in rules.stop_drug_ids
        and (order.route or "").upper() in rules.stop_routes
    )


def running_ketoacidosis_infusions(orders: Iterable[Order]) -> list[Order]:
    """The running intravenous insulin, saline and potassium orders."""
    return [o for o in orders if _is_infusion_order(o)]


def _latest(results: Iterable[OrderResult], lab: str, before: datetime) -> float | None:
    series = [
        (r.result_datetime, float(r.value))
        for r in results
        if r.lab_name == lab and isinstance(r.value, (int, float)) and r.result_datetime < before
    ]
    return max(series)[1] if series else None


def ketoacidosis_resolved(results: Iterable[OrderResult], at: datetime) -> bool:
    """Whether the labs resulted before ``at`` meet the resolution criteria:
    the latest pH or bicarbonate reaches its limit and the latest ketone (when
    resulted) is below its limit."""
    rules = ketoacidosis_resolution_rules()
    results = list(results)
    ph = _latest(results, rules.ph_lab, at)
    hco3 = _latest(results, rules.bicarbonate_lab, at)
    ketone = _latest(results, rules.ketone_lab, at)
    acid_base_ok = (ph is not None and ph >= rules.ph_min) or (hco3 is not None and hco3 >= rules.bicarbonate_min)
    return acid_base_ok and (ketone is None or ketone < rules.ketone_max_mmol_l)


def ketoacidosis_transition_due(orders: Iterable[Order], results: Iterable[OrderResult], day_start: datetime) -> bool:
    """Whether the stay switches to subcutaneous insulin at ``day_start``: an
    insulin infusion runs and DKA is resolved, or the infusion reached
    ``max_infusion_days``."""
    rules = ketoacidosis_resolution_rules()
    insulin = [o for o in running_ketoacidosis_infusions(orders) if o.drug_id == rules.infusion_insulin_drug_id]
    if not insulin:
        return False
    began = min(o.ordered_datetime for o in insulin)
    if day_start - began >= timedelta(days=rules.max_infusion_days):
        return True
    return ketoacidosis_resolved(results, day_start)


def basal_regimen_entry(protocol_drugs: dict[str, Any], country_key: str) -> dict[str, Any] | None:
    """The protocol's basal subcutaneous insulin entry for ``country_key``
    (``None`` when it lists none)."""
    from clinosim.modules.disease.localization import _country_to_yaml_key

    rules = ketoacidosis_resolution_rules()
    block = (protocol_drugs or {}).get(rules.regimen_block)
    entries = block.get(_country_to_yaml_key(country_key)) if isinstance(block, dict) else block
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("drug_id") == rules.basal_drug_id:
            return entry
    return None


def stop_ketoacidosis_infusions(orders: Iterable[Order], at: datetime) -> list[Order]:
    """End every running ketoacidosis infusion order ``overlap_hours`` after
    ``at`` (its order time when that is later); return them."""
    end = at + timedelta(hours=ketoacidosis_resolution_rules().overlap_hours)
    stopped = running_ketoacidosis_infusions(orders)
    for order in stopped:
        order.status = OrderStatus.STOPPED
        order.end_datetime = max(end, order.ordered_datetime)
    return stopped
