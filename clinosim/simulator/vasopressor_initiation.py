"""Starting a vasopressor infusion from the recorded blood pressure (Issue #3332).

A vasopressor is started when the simulated pressure is low despite fluids,
not on a fixed hospital day: once the day's vital signs are recorded, a stay
whose protocol names a vasopressor and that has none running starts the
protocol's first-line vasopressor when ``min_low_readings`` mean arterial
pressures of the day are below the target, recorded after the fluid
resuscitation window (``vasopressor_start_time``). The target is the one of
the weaning rule (``vasoactive_weaning.yaml``), so a vasopressor is started
below the pressure it is weaned to. Fixed-day vasopressor starts of the disease
protocols are not applied on their day (``is_vasopressor_start``); a second
vasopressor listed there starts only while a vasopressor runs and the pressure
stays low (``add_on_vasopressor_indicated``). Values live in
``reference_data/vasopressor_initiation.yaml``. Everything here is RNG-free.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim.codes.drugs import drug_classes, protocol_drug_name
from clinosim.datafiles import load_data_yaml
from clinosim.modules.disease.localization import _country_to_yaml_key, archetype_start_entries
from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.modules.order.absolute_dose import is_continuous_infusion
from clinosim.simulator.vasoactive_support import mean_arterial_pressure, vasoactive_weaning_rules
from clinosim.types.encounter import Order, OrderStatus, OrderType, VitalSignRecord

_DAY_END = timedelta(days=1) - timedelta(minutes=1)


class VasopressorInitiationRules(BaseModel):
    """Schema of ``reference_data/vasopressor_initiation.yaml`` (Issue #3332)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_low_readings: int = Field(ge=1)
    fluid_resuscitation_hours: float = Field(ge=0)
    order_delay_minutes: int = Field(ge=0)
    fluid_drug_ids: tuple[str, ...]


@functools.cache
def vasopressor_initiation_rules() -> VasopressorInitiationRules:
    """The validated vasopressor-initiation rules."""
    return VasopressorInitiationRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "vasopressor_initiation.yaml")
    )


def is_vasopressor_start(spec: Any) -> bool:
    """Whether a protocol drug entry starts a vasopressor given as a continuous
    infusion (not an oral vasopressor such as midodrine, nor a one-time dose)."""
    if not isinstance(spec, dict):
        return False
    name = protocol_drug_name(spec)
    classes = drug_classes(str(spec.get("drug_id") or name))
    if "vasopressor" not in classes or "vasopressor.oral" in classes:
        return False
    return is_continuous_infusion("", f"{name} {spec.get('dose', '')}")


def _section_entries(section: Any, country_key: str) -> list:
    if isinstance(section, list):
        return section
    if isinstance(section, dict):
        entries = section.get(_country_to_yaml_key(country_key)) or []
        return entries if isinstance(entries, list) else []
    return []


def _archetype_vasopressors(protocol: DiseaseProtocol, archetype: str, country_key: str) -> list[dict]:
    mods = (protocol.course_archetypes or {}).get(archetype, {}).get("treatment_modifications", {})
    found: list[dict] = []
    for _day, mod in sorted(mods.items(), key=lambda kv: int(str(kv[0]).removeprefix("day_") or 0)):
        found.extend(e for e in archetype_start_entries(mod, country_key) if is_vasopressor_start(e))
    return found


def first_line_vasopressor(protocol: DiseaseProtocol, archetype: str, country_key: str) -> dict | None:
    """The vasopressor the protocol starts first for ``country_key``: the
    stay's archetype's own first vasopressor start, else a vasopressor of the
    protocol's ``vasopressors`` or ``escalation`` blocks, else the first
    vasopressor start of any archetype; ``None`` when the protocol names none
    (no vasopressor is indicated)."""
    found = _archetype_vasopressors(protocol, archetype, country_key)
    if found:
        return found[0]
    drugs = protocol.drugs or {}
    for block in ("vasopressors", "escalation"):
        for entry in _section_entries(drugs.get(block), country_key):
            if is_vasopressor_start(entry):
                return entry
    for other in protocol.course_archetypes or {}:
        found = _archetype_vasopressors(protocol, other, country_key)
        if found:
            return found[0]
    return None


def _drug_of(order: Order) -> str:
    return order.drug_id or protocol_drug_name({"drug": order.display_name})


def _is_vasopressor_infusion(order: Order) -> bool:
    return (
        order.order_type == OrderType.MEDICATION
        and not (order.display_name or "").startswith("DISCONTINUE:")
        and not order.single_dose
        and is_vasopressor_start(
            {
                "drug_id": order.drug_id,
                "drug": order.display_name,
                "dose": f"{order.display_name} {order.frequency or ''}",
            }
        )
    )


def running_vasopressors(orders: Iterable[Order]) -> list[Order]:
    """The placed (running) vasopressor infusion orders."""
    return [o for o in orders if o.status == OrderStatus.PLACED and _is_vasopressor_infusion(o)]


def _low(v: VitalSignRecord) -> bool:
    return (
        v.systolic_bp is not None
        and v.diastolic_bp is not None
        and mean_arterial_pressure(v.systolic_bp, v.diastolic_bp) < vasoactive_weaning_rules().map_target_mmhg
    )


def fluids_ready_at(orders: Iterable[Order]) -> datetime | None:
    """When the stay's fluid resuscitation window ends: the first IV fluid order
    plus ``fluid_resuscitation_hours``; ``None`` when no fluid was ordered."""
    rules = vasopressor_initiation_rules()
    times = [
        o.ordered_datetime
        for o in orders
        if o.order_type == OrderType.MEDICATION and _drug_of(o) in rules.fluid_drug_ids
    ]
    return min(times) + timedelta(hours=rules.fluid_resuscitation_hours) if times else None


def vasopressor_start_time(
    orders: Iterable[Order], vitals_today: Iterable[VitalSignRecord], day_start: datetime
) -> datetime | None:
    """When to order the first-line vasopressor from today's recorded pressures,
    or ``None``: no vasopressor runs, and ``min_low_readings`` mean arterial
    pressures below the target were recorded after the fluid window; the time is
    ``order_delay_minutes`` after the last of them, within the day."""
    orders = list(orders)
    if running_vasopressors(orders):
        return None
    rules = vasopressor_initiation_rules()
    ready = fluids_ready_at(orders)
    low = sorted(v.timestamp for v in vitals_today if _low(v) and (ready is None or v.timestamp >= ready))
    if len(low) < rules.min_low_readings:
        return None
    start = low[rules.min_low_readings - 1] + timedelta(minutes=rules.order_delay_minutes)
    return min(start, day_start + _DAY_END)


def add_on_vasopressor_indicated(orders: Iterable[Order], vitals: Iterable[VitalSignRecord], at: datetime) -> bool:
    """Whether a second vasopressor may start at ``at``: a vasopressor infusion
    runs and a mean arterial pressure recorded after it started, before ``at``,
    was below the target (hypotension persisting on support)."""
    running = running_vasopressors(orders)
    if not running:
        return False
    since = min(
        max(o.ordered_datetime, o.administer_from) if o.administer_from else o.ordered_datetime for o in running
    )
    return any(_low(v) and since <= v.timestamp < at for v in vitals)
