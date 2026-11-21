"""When a catheter is placed and when its indication ends (Issue #3516).

A urinary or central venous catheter is placed by an insertion procedure or a
catheter order (an ICU device with neither: on the ICU transfer day) and is
removed on the first day its indication has ended: after the operation for a
post-operative catheter, after the minimum dwell for strict intake and output
monitoring or haemodynamic monitoring, and in each case only once the patient
needs no ICU-level care (``daily_loop.icu_escalation_needed``). A catheter
whose indication never ends is removed on the discharge date. Values and
sources live in ``reference_data/device_removal.yaml``. Everything here is
RNG-free.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim.codes.snomed_concepts import SURGICAL_PROCEDURE
from clinosim.datafiles import load_data_yaml
from clinosim.modules._shared import get_attr_or_key as _get


class IndicationRule(BaseModel):
    """One reason a device stays and when it ends."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    when: Literal["always", "surgery_in_stay"]
    anchor: Literal["placement", "last_surgery"]
    days_after_anchor: int = Field(ge=0)
    stable_consecutive_days: int = Field(ge=1)


class DeviceKindRule(BaseModel):
    """Placement events and indications of one device type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    procedure_types: tuple[str, ...] = Field(min_length=1)
    order_patterns: tuple[str, ...]
    indications: dict[str, IndicationRule]

    @field_validator("procedure_types")
    @classmethod
    def _catalog_procedures(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        from clinosim.codes.procedures import catalog_procedure_types

        unknown = sorted(set(v) - catalog_procedure_types())
        if unknown:
            raise ValueError(f"procedure types {unknown} are not in the procedure catalog")
        return v

    @field_validator("order_patterns")
    @classmethod
    def _compiles(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in v:
            re.compile(pattern)
        return v


class DeviceRemovalRules(BaseModel):
    """Schema of ``reference_data/device_removal.yaml`` (Issue #3516)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kinds: dict[str, DeviceKindRule] = Field(min_length=1)

    @field_validator("kinds")
    @classmethod
    def _device_types(cls, v: dict[str, DeviceKindRule]) -> dict[str, DeviceKindRule]:
        from clinosim.modules.device.engine import load_devices_config

        unknown = sorted(set(v) - set(load_devices_config()["devices"]))
        if unknown:
            raise ValueError(f"device types {unknown} are not in devices.yaml")
        return v


@functools.cache
def device_removal_rules() -> DeviceRemovalRules:
    """The validated catheter placement and removal rules."""
    return DeviceRemovalRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "device_removal.yaml")
    )


def _to_date(value: Any) -> date | None:
    from clinosim.timeutil import parse_iso_datetime

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = parse_iso_datetime(value, lenient=True)
    return parsed.date() if parsed is not None else None


def placing_date(rule: DeviceKindRule, record: Any, encounter: Any) -> date | None:
    """Date of the earliest insertion procedure or catheter order of the
    encounter, ``None`` when there is none."""
    enc_id = str(_get(encounter, "encounter_id", "") or "")
    dates: list[date] = []
    for p in _get(record, "procedures", []) or []:
        if str(_get(p, "encounter_id", "") or "") == enc_id and _get(p, "procedure_type", "") in rule.procedure_types:
            if (d := _to_date(_get(p, "start_datetime", None))) is not None:
                dates.append(d)
    patterns = [re.compile(p, re.IGNORECASE) for p in rule.order_patterns]
    if patterns:
        for o in _get(record, "orders", []) or []:
            if str(_get(o, "encounter_id", "") or "") != enc_id or str(_get(o, "status", "") or "") == "cancelled":
                continue
            text = f"{_get(o, 'display_name', '')} {_get(o, 'order_code', '')}"
            if any(p.search(text) for p in patterns) and (d := _to_date(_get(o, "ordered_datetime", None))) is not None:
                dates.append(d)
    return min(dates) if dates else None


def surgery_dates(record: Any, encounter: Any) -> list[date]:
    """Dates of the surgical procedures of the encounter."""
    enc_id = str(_get(encounter, "encounter_id", "") or "")
    out: list[date] = []
    for p in _get(record, "procedures", []) or []:
        if str(_get(p, "encounter_id", "") or "") == enc_id and _get(p, "category_code", "") == SURGICAL_PROCEDURE:
            if (d := _to_date(_get(p, "start_datetime", None))) is not None:
                out.append(d)
    return out


def removal_date(
    rule: DeviceKindRule,
    *,
    placed: date,
    admitted: date,
    discharged: date | None,
    states: Sequence[Any],
    operations: Sequence[date],
) -> tuple[date | None, str]:
    """``(removal date, indication)`` of a device placed on ``placed``.

    The indication is the first of the rule's whose condition holds; the
    device is removed on the first day on or after its end that the patient
    needed no ICU-level care for the required run of days, clipped to the
    discharge date (``None`` while the stay is open). A device type without
    indications is removed at discharge."""
    from clinosim.simulator.daily_loop import icu_escalation_needed

    for name, ind in rule.indications.items():
        if ind.when == "surgery_in_stay" and not operations:
            continue
        anchor = placed if ind.anchor == "placement" else max(operations)
        if discharged is None:
            # An ongoing stay keeps its device open: the simulated days past
            # the snapshot are not part of the record (as for its orders).
            return None, name
        day = max(placed, anchor + timedelta(days=ind.days_after_anchor))
        while day <= discharged:
            run = [(day + timedelta(days=k) - admitted).days for k in range(ind.stable_consecutive_days)]
            if all(0 <= i < len(states) and not icu_escalation_needed(states[i]) for i in run):
                return day, name
            day += timedelta(days=1)
        return discharged, name
    return discharged, ""
