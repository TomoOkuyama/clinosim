"""Supersede earlier medication orders (Issue #2615).

A POST_ENCOUNTER enricher: within each record, a medication order for a drug
that already has an active order (or a class switch listed in
``reference_data/medication_supersede.yaml``) stops the earlier order at the
new order's time, drops the earlier order's administrations from then on, and
links the new order to it (``Order.prior_order_id`` →
``MedicationRequest.priorPrescription``).

Runs after the daily loop, like ``discontinue_flip``: the per-day MAR
generation has finished, so stopping an order here moves no random draw
(AD-16). RNG-free.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from clinosim.codes.drugs import all_drug_ids, drug_classes, drug_ref, get_drug
from clinosim.datafiles import load_validated_yaml
from clinosim.modules._shared import MED_STOP_ORDER_ID_MARKER
from clinosim.types.encounter import OrderStatus, OrderType

_REF = Path(__file__).parent / "reference_data" / "medication_supersede.yaml"
_INACTIVE = (OrderStatus.STOPPED, OrderStatus.CANCELLED)
_STAY_TYPES = frozenset({"inpatient", "icu", "rehab_inpatient"})


def _check_class(name: str) -> str:
    """``name`` is a class of some catalog drug (else the rule never fires)."""
    if name not in {c for d in all_drug_ids() for c in drug_classes(d)}:
        raise ValueError(f"drug class {name!r} is not a class of any catalog drug")
    return name


class _ClassSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_class: StrictStr
    stops: list[StrictStr] = Field(min_length=1)

    @field_validator("new_class")
    @classmethod
    def _new_class_known(cls, v: str) -> str:
        return _check_class(v)

    @field_validator("stops")
    @classmethod
    def _stops_known(cls, v: list[str]) -> list[str]:
        return [_check_class(c) for c in v]


class MedicationSupersede(BaseModel):
    """Shape of ``medication_supersede.yaml``."""

    model_config = ConfigDict(extra="forbid")

    class_switches: list[_ClassSwitch] = []
    prn_markers: list[Annotated[StrictStr, Field(min_length=1)]] = Field(min_length=1)


@cache
def _supersede_config() -> dict[str, Any]:
    return load_validated_yaml(_REF, MedicationSupersede)


@cache
def _class_switches() -> tuple[tuple[str, frozenset[str]], ...]:
    rules = (_supersede_config() or {}).get("class_switches") or []
    return tuple((str(r["new_class"]), frozenset(str(c) for c in r["stops"])) for r in rules)


@cache
def _prn_markers() -> tuple[str, ...]:
    return tuple(str(m) for m in (_supersede_config() or {}).get("prn_markers") or ("PRN",))


def _drug_id(order: Any) -> str:
    return str(getattr(order, "drug_id", "") or "") or drug_ref(str(getattr(order, "display_name", "") or ""))


def _classes(drug_id: str) -> frozenset[str]:
    drug = get_drug(drug_id) if drug_id else None
    return frozenset(drug.classes) if drug is not None else frozenset()


def _supersedes(new_id: str, old_id: str) -> bool:
    """True when an order for ``new_id`` replaces an active order for ``old_id``."""
    if new_id == old_id:
        return True
    new_classes, old_classes = _classes(new_id), _classes(old_id)
    return any(new in new_classes and old_classes & stops for new, stops in _class_switches())


def _is_prescription(order: Any) -> bool:
    if getattr(order, "order_type", None) != OrderType.MEDICATION:
        return False
    if MED_STOP_ORDER_ID_MARKER in str(getattr(order, "order_id", "")):
        return False
    return not str(getattr(order, "display_name", "") or "").startswith("DISCONTINUE:")


def _is_prn(order: Any) -> bool:
    """An as-needed order: ``frequency`` or the order text carries a ``prn_markers`` entry."""
    text = f"{getattr(order, 'frequency', '') or ''} {getattr(order, 'display_name', '') or ''}".upper()
    return any(marker.upper() in text for marker in _prn_markers())


def supersede_orders(orders: list[Any], administrations: list[Any]) -> list[Any]:
    """Stop superseded orders in place; return the administrations kept."""
    meds = sorted(
        (o for o in orders if _is_prescription(o) and getattr(o, "ordered_datetime", None) is not None),
        key=lambda o: o.ordered_datetime,
    )
    # The switch happens when the new drug is first given, which can precede
    # the order's recorded time (an administration charted before the order).
    first_given: dict[str, Any] = {}
    for mar in administrations:
        when = getattr(mar, "actual_datetime", None) or getattr(mar, "scheduled_datetime", None)
        oid = getattr(mar, "order_id", "")
        if when is not None and (oid not in first_given or when < first_given[oid]):
            first_given[oid] = when
    stopped_at: dict[str, Any] = {}
    for i, new in enumerate(meds):
        new_id = _drug_id(new)
        if not new_id:
            continue
        for old in meds[:i]:
            if (
                old.status in _INACTIVE
                or old.encounter_id != new.encounter_id
                or old.ordered_datetime >= new.ordered_datetime
                # A PRN order alongside a scheduled one (breakthrough dosing)
                # is a combination, not a replacement.
                or _is_prn(old) != _is_prn(new)
            ):
                continue
            old_id = _drug_id(old)
            if old_id and _supersedes(new_id, old_id):
                old.status = OrderStatus.STOPPED
                switch = min(new.ordered_datetime, first_given.get(new.order_id, new.ordered_datetime))
                stopped_at[old.order_id] = min(stopped_at.get(old.order_id, switch), switch)
                if old_id == new_id and not getattr(new, "prior_order_id", ""):
                    new.prior_order_id = old.order_id
    if not stopped_at:
        return administrations
    kept = []
    for mar in administrations:
        cut = stopped_at.get(getattr(mar, "order_id", ""))
        when = getattr(mar, "actual_datetime", None) or getattr(mar, "scheduled_datetime", None)
        if cut is not None and when is not None and when >= cut:
            continue
        kept.append(mar)
    return kept


def _finished_stays(encounters: list[Any]) -> dict[str, Any]:
    out = {}
    for enc in encounters:
        etype = str(getattr(getattr(enc, "encounter_type", ""), "value", getattr(enc, "encounter_type", "")))
        status = str(getattr(getattr(enc, "status", ""), "value", getattr(enc, "status", "")))
        if etype in _STAY_TYPES and status == "completed" and getattr(enc, "discharge_datetime", None):
            out[str(enc.encounter_id)] = enc.discharge_datetime
    return out


def close_orders_at_discharge(encounters: list[Any], orders: list[Any], administrations: list[Any]) -> None:
    """Close the medication orders of a finished stay (Issue #2606).

    Each prescription of a completed inpatient stay gets ``end_datetime``:
    its last administration, or the discharge when it was never given. The
    FHIR MedicationRequest of an order with an end is ``completed`` (or keeps
    ``stopped``) and its timing carries ``boundsPeriod.end``. An ongoing stay
    keeps its orders open. RNG-free.
    """
    discharge = _finished_stays(encounters)
    if not discharge:
        return
    last_given: dict[str, Any] = {}
    for mar in administrations:
        when = getattr(mar, "actual_datetime", None) or getattr(mar, "scheduled_datetime", None)
        oid = str(getattr(mar, "order_id", "") or "")
        if when is not None and (oid not in last_given or when > last_given[oid]):
            last_given[oid] = when
    for order in orders:
        if not _is_prescription(order) or getattr(order, "end_datetime", None) is not None:
            continue
        end = discharge.get(str(getattr(order, "encounter_id", "") or ""))
        if end is None or getattr(order, "status", None) == OrderStatus.CANCELLED:
            continue
        order.end_datetime = last_given.get(str(order.order_id), end)


def enrich_supersede_orders(ctx: Any) -> None:
    """POST_ENCOUNTER enricher entry point."""
    for record in ctx.records:
        orders = getattr(record, "orders", None) or []
        mars = getattr(record, "medication_administrations", None) or []
        record.medication_administrations = supersede_orders(orders, mars)
        close_orders_at_discharge(getattr(record, "encounters", None) or [], orders, record.medication_administrations)
