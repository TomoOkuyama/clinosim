"""Executing the actions a complication declares (Issues #3543, #3639, #3864).

A disease YAML lists ``actions`` on a complication. Only ``icu_transfer`` was
ever acted on, so an infectious complication (aspiration pneumonia, urinary
tract infection, surgical site infection, sepsis, ...) got no antibiotic. This
module resolves the antibiotic actions: the one canonical spelling of an
action, and the empirical regimen of a complication, taken from the first-line
antibiotics of the disease protocol that the reference data names for it. The
airway action (intubation / mechanical ventilation, Issue #3639) is resolved
here too, and (Issue #3864) the anticoagulation / acid-suppression treatment
actions: therapeutic anticoagulation of a venous thromboembolism, the hold of a
running anticoagulant on a bleed, and the IV PPI of a gastrointestinal bleed
(regimens from the protocols the reference data names, renal handling from the
entry's ``renal_adjustment``, the discharge continuation of a started
anticoagulant); the diagnosis a complication gives the stay is in
``complication_dx`` (Issue #3673).
Values live in ``reference_data/complication_actions.yaml``. Everything here is
RNG-free.
"""

from __future__ import annotations

import functools
import math
import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from clinosim.codes.drugs import drug_classes
from clinosim.datafiles import load_data_yaml
from clinosim.modules._shared import COMPLICATION_TREATMENT_ORDER_ID_MARKER
from clinosim.types.encounter import Order, OrderStatus, OrderType

_Slug = StrictStr


class SeverityCriterion(BaseModel):
    """One lab limit of a severity rule (Issue #3896): the latest result of
    ``lab`` at or before the onset is ``at_least`` (>=) or ``above`` (>) the
    limit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lab: _Slug
    at_least: float | None = None
    above: float | None = None

    @model_validator(mode="after")
    def _one_limit(self) -> SeverityCriterion:
        if (self.at_least is None) == (self.above is None):
            raise ValueError("a severity criterion has either at_least or above")
        return self


class SeverityRule(BaseModel):
    """A stay is ``severe`` when any criterion holds, else ``non_severe``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criteria: tuple[SeverityCriterion, ...] = Field(min_length=1)


class TreatmentAction(BaseModel):
    """One executed treatment action (Issue #3864): the regimen is the entries
    of a protocol block (``protocol`` + ``block``), ``regimen`` (country ->
    entries, authored in the reference data, where no protocol has one) or
    ``regimen_by_severity`` (severity -> country -> entries, with the
    ``severity`` rule that picks the level), and ``drug_class`` / ``route``
    choose among them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: _Slug | None = None
    block: _Slug | None = None
    regimen: dict[_Slug, tuple[dict[str, Any], ...]] | None = None
    regimen_by_severity: dict[_Slug, dict[_Slug, tuple[dict[str, Any], ...]]] | None = None
    severity: SeverityRule | None = None
    intent: _Slug
    drug_class: _Slug
    route: _Slug | None = None
    discharge_block: _Slug | None = None
    course_days: int | None = Field(default=None, gt=0)
    first_only: bool = False
    lead_in_days: int | None = Field(default=None, gt=0)
    blocked_by: tuple[_Slug, ...] = ()

    @model_validator(mode="after")
    def _one_regimen_source(self) -> TreatmentAction:
        sources = [
            self.regimen is not None,
            self.regimen_by_severity is not None,
            self.protocol is not None and self.block is not None,
        ]
        if sum(sources) != 1:
            raise ValueError("a treatment action names one of protocol + block, regimen, regimen_by_severity")
        if (self.regimen_by_severity is None) != (self.severity is None):
            raise ValueError("regimen_by_severity and severity go together")
        if self.regimen_by_severity is not None and set(self.regimen_by_severity) != {"non_severe", "severe"}:
            raise ValueError("regimen_by_severity has the levels non_severe and severe")
        return self


class StopAction(BaseModel):
    """One executed stop action (Issue #3864): the running drugs of ``classes``
    (not those of ``spared_classes``) are stopped at the onset order time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    classes: tuple[_Slug, ...] = Field(min_length=1)
    spared_classes: tuple[_Slug, ...] = ()
    intent: _Slug
    planned_prophylaxis: bool = False


class ComplicationActionRules(BaseModel):
    """Schema of ``reference_data/complication_actions.yaml`` (Issue #3543)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    order_hour: int = Field(ge=0, le=23)
    aliases: dict[_Slug, _Slug]
    antibiotic_actions: dict[_Slug, dict[_Slug, _Slug]] = Field(min_length=1)
    no_regimen: tuple[_Slug, ...]
    not_executed_antibiotic_actions: tuple[_Slug, ...]
    airway_actions: tuple[_Slug, ...] = Field(min_length=1)
    not_executed_airway_actions: tuple[_Slug, ...]
    treatment_actions: dict[_Slug, TreatmentAction]
    stop_actions: dict[_Slug, StopAction] = Field(min_length=1)
    not_executed_treatment_actions: tuple[_Slug, ...]


@functools.cache
def complication_action_rules() -> ComplicationActionRules:
    """The validated complication-action rules."""
    return ComplicationActionRules.model_validate(
        load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "complication_actions.yaml")
    )


def canonical_action(action: str) -> str:
    """The canonical spelling of a complication action."""
    return complication_action_rules().aliases.get(action, action)


def antibiotic_actions_of(complication: dict[str, Any]) -> list[str]:
    """The canonical executed antibiotic actions a complication declares, in
    order and without repeats."""
    rules = complication_action_rules()
    out: dict[str, None] = {}
    for action in complication.get("actions", []) or []:
        if isinstance(action, str) and canonical_action(action) in rules.antibiotic_actions:
            out.setdefault(canonical_action(action))
    return list(out)


def airway_actions_of(complication: dict[str, Any]) -> list[str]:
    """The canonical executed airway actions a complication declares (``intubate``
    for intubation / mechanical ventilation), in order and without repeats."""
    rules = complication_action_rules()
    out: dict[str, None] = {}
    for action in complication.get("actions", []) or []:
        if isinstance(action, str) and canonical_action(action) in rules.airway_actions:
            out.setdefault(canonical_action(action))
    return list(out)


def regimen_protocol_id(action: str, complication_name: str) -> str | None:
    """The disease protocol whose first-line antibiotics are the empirical
    regimen of ``complication_name`` for ``action``, ``None`` when none is
    named."""
    return complication_action_rules().antibiotic_actions.get(action, {}).get(complication_name)


def first_line_antibiotics(first_line_block: Any, country_key: str) -> list[dict[str, Any]]:
    """The one empirical antibiotic of a ``drugs.first_line`` block for
    ``country_key``: its first entry of catalog class ``antibiotic`` that is
    ordered without a draw (no ``probability``). A block lists alternatives and
    add-on agents (a second first-line drug, an atypical-coverage drug) that
    a complication's empirical order does not repeat; ``[]`` when none."""
    if not isinstance(first_line_block, dict):
        return []
    entries = first_line_block.get(country_key, [])
    if isinstance(entries, dict):
        entries = [entries]
    for e in entries:
        if (
            isinstance(e, dict)
            and e.get("probability") is None
            and "antibiotic" in drug_classes(str(e.get("drug_id") or e.get("drug") or ""))
        ):
            return [e]
    return []


def treatment_actions_of(complication: dict[str, Any]) -> list[str]:
    """The canonical executed anticoagulation / PPI actions a complication
    declares (``start_anticoagulation``, ``IV_PPI``), in order and without
    repeats (Issue #3864)."""
    rules = complication_action_rules()
    out: dict[str, None] = {}
    for action in complication.get("actions", []) or []:
        if isinstance(action, str) and canonical_action(action) in rules.treatment_actions:
            out.setdefault(canonical_action(action))
    return list(out)


def stop_actions_of(complication: dict[str, Any]) -> list[str]:
    """The canonical executed stop actions a complication declares
    (``hold_anticoagulation``, ``stop_offending_antibiotic``), in order and
    without repeats (Issue #3864)."""
    rules = complication_action_rules()
    out: dict[str, None] = {}
    for action in complication.get("actions", []) or []:
        if isinstance(action, str) and canonical_action(action) in rules.stop_actions:
            out.setdefault(canonical_action(action))
    return list(out)


_BELOW = re.compile(r"^eGFR_below_(\d+)$")
_RANGE = re.compile(r"^eGFR_(\d+)_(\d+)$")


def renal_decision(adjustment: dict[str, Any] | None, crcl_ml_min: float | None) -> str | None:
    """What an entry's ``renal_adjustment`` ("eGFR_below_30: avoid",
    "eGFR_15_50: 30mg PO daily") says for a creatinine clearance: ``"avoid"``,
    a replacement dose text, or ``None`` (no change, or no clearance known).
    The Cockcroft-Gault clearance stands for the eGFR the protocols write.
    The most restrictive threshold that applies decides."""
    if not adjustment or crcl_ml_min is None:
        return None
    below = sorted((int(m.group(1)), str(v)) for k, v in adjustment.items() if (m := _BELOW.match(k)))
    for limit, decision in below:
        if crcl_ml_min < limit:
            return decision
    ranges = sorted((int(m.group(1)), int(m.group(2)), str(v)) for k, v in adjustment.items() if (m := _RANGE.match(k)))
    for low, high, decision in ranges:
        if low <= crcl_ml_min <= high:
            return decision
    return None


def treatment_severity(action: str, results: Iterable[Any], at: datetime) -> str | None:
    """The severity level (``severe`` / ``non_severe``) of an action that has a
    severity rule, from the stay's results at ``at`` (Issue #3896): severe when
    any criterion's lab, its latest result at or before ``at``, meets the
    limit; a lab with no result by then does not count. ``None`` for an action
    without a rule. Draws nothing."""
    spec = complication_action_rules().treatment_actions[action]
    if spec.severity is None:
        return None
    latest: dict[str, tuple[datetime, float]] = {}
    for r in results:
        if (
            r.lab_name
            and isinstance(r.value, (int, float))
            and r.result_datetime is not None
            and r.result_datetime <= at
        ):
            if r.lab_name not in latest or r.result_datetime >= latest[r.lab_name][0]:
                latest[r.lab_name] = (r.result_datetime, float(r.value))
    for c in spec.severity.criteria:
        if c.lab in latest:
            value = latest[c.lab][1]
            if (c.at_least is not None and value >= c.at_least) or (c.above is not None and value > c.above):
                return "severe"
    return "non_severe"


def treatment_candidates(action: str, country_key: str, severity: str | None = None) -> list[dict[str, Any]]:
    """The protocol entries a treatment action chooses from, in order (Issue
    #3864): the entries of the named block for the country whose drug is of the
    action's class (and route) and that are given without a draw (no
    ``probability``); ``first_only`` keeps the first alone. An action with
    ``regimen_by_severity`` takes the entries of ``severity`` (``non_severe``
    when not given, Issue #3896)."""
    from clinosim.modules.disease.protocol import load_disease_protocol

    spec = complication_action_rules().treatment_actions[action]
    if spec.regimen_by_severity is not None:
        entries: Any = list(spec.regimen_by_severity[severity or "non_severe"].get(country_key, ()))
    elif spec.regimen is not None:
        entries = list(spec.regimen.get(country_key, ()))
    else:
        assert spec.protocol is not None and spec.block is not None
        entries = (load_disease_protocol(spec.protocol).drugs.get(spec.block) or {}).get(country_key, [])
        if isinstance(entries, dict):
            entries = [entries]
    out = [
        e
        for e in entries
        if isinstance(e, dict)
        and e.get("probability") is None
        and spec.drug_class in drug_classes(str(e.get("drug_id") or e.get("drug") or ""))
        and (spec.route is None or str(e.get("route", "")).upper() == spec.route)
    ]
    return out[:1] if spec.first_only else out


def is_therapeutic_anticoagulant_order(order: Order) -> bool:
    """Whether a medication order gives a therapeutic anticoagulant: an oral
    anticoagulant, or a heparin as a continuous infusion (prophylactic SC
    heparin and enoxaparin are not; the rule of ``prophylaxis_rules.yaml``)."""
    from clinosim.modules.order.absolute_dose import is_continuous_infusion

    classes = drug_classes(order.drug_id or order.display_name or "")
    if "anticoagulant.vka" in classes or "anticoagulant.doac" in classes:
        return True
    return "anticoagulant.heparin" in classes and is_continuous_infusion(
        order.frequency or "", order.display_name or ""
    )


def complication_discharge_specs(
    orders: Iterable[Order], country_key: str, *, discharge_time: datetime | None = None
) -> list[dict[str, Any]]:
    """The discharge prescription entries for the treatment a complication
    started and that still runs at discharge (Issue #3864): the anticoagulant
    (:func:`_anticoagulant_discharge_specs`) and the rest of a C. difficile
    course, which ends ``duration_days`` after its order (``discharge_time``
    is needed for it); a held (stopped) order is not continued."""
    orders = list(orders)
    out = _anticoagulant_discharge_specs(orders, country_key)
    if discharge_time is not None:
        for o in orders:
            if (
                o.order_type == OrderType.MEDICATION
                and COMPLICATION_TREATMENT_ORDER_ID_MARKER in o.order_id
                and o.status == OrderStatus.PLACED
                and o.duration_days
                and o.route.upper() == "PO"
                and "antibiotic" in drug_classes(o.drug_id or o.display_name or "")
            ):
                remaining = math.ceil(
                    (o.ordered_datetime + timedelta(days=o.duration_days) - discharge_time).total_seconds() / 86400
                )
                if remaining > 0:
                    out.append(
                        {
                            "drug_id": o.drug_id,
                            "dose": f"{o.dose_quantity:g}{o.dose_unit} {o.route} {o.frequency}".strip(),
                            "route": o.route,
                            "duration_days": remaining,
                            "from_complication": True,
                        }
                    )
    return out


def complication_stopped_antibiotic_classes(orders: Iterable[Order]) -> tuple[frozenset[str], frozenset[str]]:
    """``(excluded classes, spared classes)`` of the discharge prescription of
    a stay in which a complication stopped the inciting antibiotic (a
    ``stop_offending_antibiotic`` marker, Issue #3864): the patient does not go
    home on another systemic antibiotic (the classes the action stops, less
    those it spares); the C. difficile course itself is a discharge spec of its
    own. Empty when no antibiotic was stopped."""
    from clinosim.modules._shared import COMPLICATION_HOLD_ORDER_ID_MARKER, MED_STOP_ORDER_ID_MARKER

    for o in orders:
        if (
            o.order_type == OrderType.MEDICATION
            and MED_STOP_ORDER_ID_MARKER in o.order_id
            and COMPLICATION_HOLD_ORDER_ID_MARKER in o.order_id
            and (o.display_name or "").startswith("DISCONTINUE:")
            and "antibiotic" in drug_classes(o.display_name.removeprefix("DISCONTINUE:").strip())
        ):
            spec = complication_action_rules().stop_actions["stop_offending_antibiotic"]
            return frozenset(spec.classes), frozenset(spec.spared_classes)
    return frozenset(), frozenset()


def _anticoagulant_discharge_specs(orders: list[Order], country_key: str) -> list[dict[str, Any]]:
    """The discharge prescription entries for the anticoagulant a complication
    started and that still runs at discharge (Issue #3864): the protocol's
    ``discharge_block`` entry of the same drug class, in the order's own
    regimen text when it is the drug the stay started on (rivaroxaban "15mg
    BID x21 days, then 20mg daily": the course is not complete at discharge),
    the entry's own dose otherwise (heparin in hospital, edoxaban at home).
    The entry's ``renal_adjustment`` is applied with the clearance the order was
    decided on. A held (stopped) order is not continued. Draws nothing."""
    from clinosim.modules.disease.protocol import load_disease_protocol

    spec = complication_action_rules().treatment_actions["start_anticoagulation"]
    started = [
        o
        for o in orders
        if o.order_type == OrderType.MEDICATION
        and COMPLICATION_TREATMENT_ORDER_ID_MARKER in o.order_id
        and o.status == OrderStatus.PLACED
        and "anticoagulant" in drug_classes(o.drug_id or o.display_name or "")
    ]
    if not started or spec.discharge_block is None or spec.protocol is None or spec.block is None:
        return []
    protocol = load_disease_protocol(spec.protocol)
    stay_drugs = {o.drug_id for o in started}
    crcl = next((o.renal_crcl_ml_min for o in started if o.renal_crcl_ml_min is not None), None)
    first_line = {e.get("drug_id"): e for e in candidates_in(protocol.drugs.get(spec.block), country_key)}
    for entry in candidates_in(protocol.drugs.get(spec.discharge_block), country_key):
        if spec.drug_class not in drug_classes(str(entry.get("drug_id") or "")):
            continue
        decision = renal_decision(entry.get("renal_adjustment"), crcl)
        if decision == "avoid":
            continue
        out = dict(entry)
        started_dose = str(first_line.get(entry.get("drug_id"), {}).get("dose", ""))
        if entry.get("drug_id") in stay_drugs and re.search(r"\bthen\b", started_dose, re.IGNORECASE):
            out["dose"] = started_dose
        elif decision:
            out["dose"] = decision
        return [out]
    return []


def candidates_in(block: Any, country_key: str) -> list[dict[str, Any]]:
    """The dict entries of a protocol drug block for ``country_key``."""
    entries = block.get(country_key, []) if isinstance(block, dict) else []
    if isinstance(entries, dict):
        entries = [entries]
    return [e for e in entries if isinstance(e, dict)]
