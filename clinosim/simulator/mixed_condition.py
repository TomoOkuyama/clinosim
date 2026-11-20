"""The co-disease of a mixed admission (Issue #3392).

An admission with ``condition_type == "mixed"`` has two diseases: the primary
one and a co-disease (``helpers._select_secondary_disease``). The co-disease
raises fever, hypoxemia and CRP from the admission, so it is also

* coded: its ICD code is a secondary diagnosis of the encounter
  (``inpatient._derive_final_diagnosis``);
* worked up and treated: its protocol's admission orders (labs, studies,
  first-line drugs, supportive care) are merged into the stay's
  (:func:`co_disease_orders`), on the admission day or, for a co-disease
  recognised late, on hospital day 1-3 (:func:`co_disease_recognition_day`);
* given a course: from the treatment day the axes its onset raised return to
  where they were (:class:`CoDiseaseCourse`).

The values are in ``reference_data/mixed_condition.yaml``. Everything here is
RNG-neutral for the stay: decisions follow a SHA of the encounter id and the
orders are placed with their own seeded RNG (``seeding.co_disease_orders_seed``).
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim import determinism
from clinosim.datafiles import load_data_yaml
from clinosim.modules._shared import CO_DISEASE_SEVERITY, ORDER_SET_ADMISSION_CARE, ORDER_SET_ADMISSION_INITIAL
from clinosim.modules.order.engine import (
    drop_legacy_duplicate_imaging,
    imaging_study_keys,
    place_admission_orders,
    place_imaging_orders,
)
from clinosim.modules.order.supersede import orders_replace_each_other
from clinosim.seeding import co_disease_orders_seed
from clinosim.types.encounter import Order, OrderType

CO_DISEASE_ID_INFIX = "C"
"""Put after ``ADM-`` in the ids of the co-disease's admission orders."""

_SUPPORTIVE_ID = re.compile(rf"-ADM-{CO_DISEASE_ID_INFIX}S\d+$")
_FIRST_LINE_ID = re.compile(rf"-ADM-{CO_DISEASE_ID_INFIX}M\d+$")


class MixedConditionRules(BaseModel):
    """Schema of ``reference_data/mixed_condition.yaml`` (Issue #3392)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    delayed_recognition_probability: float = Field(ge=0.0, le=1.0)
    recognition_day_min: int = Field(ge=1)
    recognition_day_max: int = Field(ge=1)
    recovery_days: int = Field(ge=1)
    recovered_axes: tuple[str, ...]
    always_skipped_supportive_types: tuple[str, ...]


@functools.cache
def mixed_condition_rules() -> MixedConditionRules:
    """The validated mixed-condition rules."""
    rules = MixedConditionRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "mixed_condition.yaml")
    )
    if rules.recognition_day_max < rules.recognition_day_min:
        raise ValueError("mixed_condition.yaml: recognition_day_max is below recognition_day_min")
    return rules


def co_disease_recognised_late(encounter_id: str) -> bool:
    """Whether the co-disease of the stay is recognised late (the missed
    secondary diagnosis of the stay). A SHA of the encounter id decides, with
    ``delayed_recognition_probability``."""
    return determinism.sha_bernoulli(
        f"{encounter_id}|co_disease_recognised_late", mixed_condition_rules().delayed_recognition_probability
    )


def co_disease_recognition_day(encounter_id: str) -> int:
    """The hospital day the co-disease is worked up and treated from: 0 (the
    admission), or a day between ``recognition_day_min`` and
    ``recognition_day_max`` when it is recognised late."""
    if not co_disease_recognised_late(encounter_id):
        return 0
    rules = mixed_condition_rules()
    span = rules.recognition_day_max - rules.recognition_day_min + 1
    return rules.recognition_day_min + determinism.sha_index(f"{encounter_id}|co_disease_recognition_day", span)


@dataclass
class CoDiseaseCourse:
    """What the daily loop does for the co-disease of a stay.

    ``treat_day``: the hospital day its treatment starts. ``daily_changes``:
    the daily state delta that returns each recovered axis its onset raised
    to where it was over ``recovery_days`` days, from ``treat_day`` on.
    ``deferred_orders``: its orders of a late recognition, put on the stay's
    order list at the start of ``treat_day``.
    """

    treat_day: int
    daily_changes: dict[str, float]
    recovery_days: int
    deferred_orders: list[Order] = field(default_factory=list)

    def changes_on(self, day: int) -> dict[str, float]:
        """The state deltas of hospital day ``day`` (empty outside the recovery window)."""
        if self.treat_day <= day < self.treat_day + self.recovery_days:
            return dict(self.daily_changes)
        return {}

    def orders_due(self, day: int) -> list[Order]:
        """The deferred orders to place at the start of hospital day ``day``."""
        return list(self.deferred_orders) if day == self.treat_day and self.treat_day > 0 else []


def co_disease_course(protocol: Any, treat_day: int, deferred_orders: list[Order]) -> CoDiseaseCourse:
    """The course of a treated co-disease (see :class:`CoDiseaseCourse`)."""
    rules = mixed_condition_rules()
    onset = (getattr(protocol, "initial_state_impact", None) or {}).get(CO_DISEASE_SEVERITY) or {}
    changes = {
        axis: -float(onset[axis]) / rules.recovery_days
        for axis in rules.recovered_axes
        if axis in onset and float(onset[axis]) != 0.0
    }
    return CoDiseaseCourse(
        treat_day=treat_day, daily_changes=changes, recovery_days=rules.recovery_days, deferred_orders=deferred_orders
    )


def _supportive_type(order: Order) -> str:
    """The ``type`` of a supportive order (its display name is ``<type>: <detail>``)."""
    return (order.display_name or "").split(":", 1)[0].strip()


def merge_co_disease_orders(existing: list[Order], co_orders: list[Order], co_imaging: list[Order]) -> list[Order]:
    """The orders of the co-disease that the stay does not already have.

    A lab of a test the stay orders is not ordered again; an imaging study of
    a modality and body part the stay already images is not either (the
    structured study of the co-disease replaces its own legacy order of the
    same part, ``drop_legacy_duplicate_imaging``); a supportive entry is left
    out when its type is one of ``always_skipped_supportive_types`` or the
    stay already carries an order of that type; a first-line drug is left out
    when the stay's active regimen already has it or an agent it would replace
    (the primary disease's ceftriaxone covers the co-disease: the supersede
    enricher would stop one of two beta-lactams, leaving an order that is
    never given). The drug-safety gate checks the rest against the stay's.
    """
    skipped = set(mixed_condition_rules().always_skipped_supportive_types)
    lab_names = {o.display_name for o in existing if o.order_type == OrderType.LAB}
    supportive_types = {_supportive_type(o) for o in existing if ":" in (o.display_name or "")}
    covered = imaging_study_keys(existing)

    structured = [o for o in co_imaging if not (imaging_study_keys([o]) & covered)]
    covered |= imaging_study_keys(structured)
    legacy_all = [o for o in co_orders if o.order_type == OrderType.IMAGING and not o.imaging_modality]
    legacy_ids = {
        o.order_id
        for o in drop_legacy_duplicate_imaging(legacy_all, structured)
        if not (imaging_study_keys([o]) & covered)
    }

    kept: list[Order] = []
    for o in co_orders:
        if o.order_type == OrderType.LAB:
            if o.display_name in lab_names:
                continue
            lab_names.add(o.display_name)
        elif o.order_type == OrderType.IMAGING:
            if not o.imaging_modality and o.order_id not in legacy_ids:
                continue
        elif _FIRST_LINE_ID.search(o.order_id):
            if any(orders_replace_each_other(o, e) for e in existing if e.order_type == OrderType.MEDICATION):
                continue
        elif _SUPPORTIVE_ID.search(o.order_id):
            kind = _supportive_type(o)
            if kind in skipped or kind in supportive_types:
                continue
        kept.append(o)
    return kept + structured


def co_disease_orders(
    protocol: Any,
    existing: list[Order],
    *,
    patient_id: str,
    encounter_id: str,
    admission_time: datetime,
    treat_day: int,
    country_key: str,
    ordered_by: str,
    patient_age: int,
    patient_weight_kg: float | None,
    imaging_seq: dict[str, int],
) -> list[Order]:
    """The admission orders of the co-disease protocol, merged with the stay's
    ``existing`` orders (:func:`merge_co_disease_orders`) and dated ``treat_day``
    days after the admission. Placed with the co-disease's own RNG."""
    rng = determinism.default_rng(co_disease_orders_seed(encounter_id))
    start = admission_time + timedelta(days=treat_day)
    orders = place_admission_orders(
        protocol.model_dump(),
        patient_id,
        encounter_id,
        start,
        country=country_key,
        rng=rng,
        ordered_by=ordered_by,
        patient_age=patient_age,
        patient_weight_kg=patient_weight_kg,
        id_infix=CO_DISEASE_ID_INFIX,
    )
    imaging = place_imaging_orders(
        protocol,
        encounter_id,
        patient_id,
        start,
        day_index=0,
        severity=CO_DISEASE_SEVERITY,
        rng=rng,
        sequence_counter=imaging_seq,
    )
    merged = merge_co_disease_orders(existing, orders, imaging)
    if treat_day > 0:
        # A late recognition is not part of the initial (ED) orders.
        for o in merged:
            if o.order_set == ORDER_SET_ADMISSION_INITIAL:
                o.order_set = ORDER_SET_ADMISSION_CARE
    return merged
