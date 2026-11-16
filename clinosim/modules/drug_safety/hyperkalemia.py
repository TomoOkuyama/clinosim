"""Inpatient hyperkalemia response (Issue #2981).

A resulted potassium at or above ``treat_threshold_mmol_l``
(``reference_data/hyperkalemia_response.yaml``) starts a hold on every drug in
``hold_classes`` (ACE inhibitors, ARBs, potassium-sparing diuretics) for the
rest of the stay, holds the drugs in ``hold_while_high_classes`` (digoxin)
while the potassium stays at or above the threshold, and places the country's
treatment order set (calcium, insulin, the dextrose given with it, a potassium
binder) as one-time doses. A held dose's reason is the latest potassium
resulted before it (Issue #3232).

Pure functions of the lab results — no randomness, so a stay whose potassium
never reaches the threshold is unchanged.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from clinosim.codes.drugs import drug_classes, get_drug
from clinosim.countries import country_code
from clinosim.datafiles import load_data_yaml
from clinosim.locale.i18n import t
from clinosim.modules._shared import sanitize_id_token
from clinosim.modules.drug_safety._hyperkalemia_thresholds import TREATMENT_ORDER_DELAY_MIN
from clinosim.modules.drug_safety._models import HyperkalemiaResponseFile
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType

_RULES_YAML = Path(__file__).resolve().parent / "reference_data" / "hyperkalemia_response.yaml"

_POTASSIUM_LAB = "K"
"""Canonical lab name of serum potassium (``observation`` lab catalog)."""


@functools.cache
def hyperkalemia_rules() -> HyperkalemiaResponseFile:
    """The validated hyperkalemia response rules."""
    return HyperkalemiaResponseFile.model_validate(load_data_yaml(_RULES_YAML))


def holds_for_hyperkalemia(drug: str) -> bool:
    """True when the drug (catalog id, name or order string) is held for
    hyperkalemia — it belongs to one of ``hold_classes``."""
    return bool(set(drug_classes(drug)) & set(hyperkalemia_rules().hold_classes))


def holds_while_hyperkalemic(drug: str) -> bool:
    """True when the drug is held only while the potassium is at or above the
    threshold — it belongs to one of ``hold_while_high_classes`` (Issue #3232)."""
    return bool(set(drug_classes(drug)) & set(hyperkalemia_rules().hold_while_high_classes))


def _reason(value: float) -> str:
    """The MAR hold reason — the potassium value, written the same way in
    both languages (a lab abbreviation and a unit)."""
    return f"K {value:.1f} mmol/L"


@dataclass(frozen=True)
class PotassiumHold:
    """A hyperkalemia hold: doses scheduled at or after ``since`` are held.

    ``history`` (Issue #3232): the stay's potassium results ``(resulted at,
    value)`` in time order, so each dose is judged and explained by the
    latest potassium before it; empty, the triggering value stands in."""

    since: datetime
    value: float
    history: tuple[tuple[datetime, float], ...] = ()

    @property
    def reason(self) -> str:
        """The hold reason of the triggering result."""
        return _reason(self.value)

    def latest_at(self, at: datetime) -> float:
        """The latest potassium resulted at or before ``at`` (the triggering
        value when ``history`` has none)."""
        latest = self.value
        for when, value in self.history:
            if when > at:
                break
            latest = value
        return latest

    def reason_at(self, at: datetime) -> str:
        """The hold reason of a dose scheduled at ``at``: the latest potassium."""
        return _reason(self.latest_at(at))

    def high_at(self, at: datetime) -> bool:
        """True when the latest potassium at ``at`` is at or above the
        threshold (a ``hold_while_high_classes`` drug is held)."""
        return at >= self.since and self.latest_at(at) >= hyperkalemia_rules().treat_threshold_mmol_l


def potassium_history(results: Iterable[OrderResult]) -> tuple[tuple[datetime, float], ...]:
    """Every numeric potassium result ``(resulted at, value)`` in time order."""
    return tuple(
        sorted(
            (r.result_datetime, float(r.value))
            for r in results
            if r.lab_name == _POTASSIUM_LAB and isinstance(r.value, (int, float))
        )
    )


def potassium_hold_from_results(results: Iterable[OrderResult]) -> PotassiumHold | None:
    """The hold the earliest potassium result at or above the threshold
    starts, or ``None`` when no result reaches it."""
    threshold = hyperkalemia_rules().treat_threshold_mmol_l
    hits: list[tuple[datetime, float]] = []
    for r in results:
        if r.lab_name != _POTASSIUM_LAB or not isinstance(r.value, (int, float)):
            continue
        if float(r.value) >= threshold:
            hits.append((r.result_datetime, float(r.value)))
    if not hits:
        return None
    since, value = min(hits)
    return PotassiumHold(since=since, value=value)


def hyperkalemia_treatment_orders(
    hold: PotassiumHold,
    *,
    patient_id: str,
    encounter_id: str,
    country: str,
    day: int,
    ordered_by: str = "",
    continuing: bool = False,
    parse_dose: Callable[[str], Mapping[str, Any]] | None = None,
) -> list[Order]:
    """The country's hyperkalemia order set for a potassium result: one-time
    doses ordered shortly after the result. ``continuing`` — the potassium was
    already at or above the threshold the day before: only the ``ongoing``
    entries (the potassium binder) are ordered again; calcium, insulin and
    the dextrose given with the insulin are given at the start of an episode.

    ``parse_dose`` (Issue #3232): the order dose parser (the order module's
    ``parse_dose_string``), applied to the entry's ``dose`` so a drug name
    that carries a strength ("Dextrose 50%") is not read as the dose."""
    ordered = (hold.since + timedelta(minutes=TREATMENT_ORDER_DELAY_MIN)).replace(second=0, microsecond=0)
    value = f"{hold.value:.1f}"
    orders: list[Order] = []
    for entry in hyperkalemia_rules().treatment.get(country_code(country), []):
        if continuing and not entry.ongoing:
            continue
        drug = get_drug(entry.drug_id)
        assert drug is not None  # validated at load
        parsed = parse_dose(entry.dose) if parse_dose is not None else {}
        orders.append(
            Order(
                order_id=f"ORD-{encounter_id}-HYPERK-D{day}-{sanitize_id_token(entry.drug_id, 12)}",
                encounter_id=encounter_id,
                patient_id=patient_id,
                order_type=OrderType.MEDICATION,
                display_name=f"{drug.names['en']} {entry.dose}",
                urgency="stat",
                clinical_intent=t("order_intent.hyperkalemia_treatment", "en", value=value),
                clinical_intent_ja=t("order_intent.hyperkalemia_treatment", "ja", value=value),
                ordered_datetime=ordered,
                ordered_by=ordered_by,
                status=OrderStatus.PLACED,
                frequency="once",
                frequency_per_day=1,
                single_dose=True,
                dose_text_en=entry.dose_text.en,
                dose_text_ja=entry.dose_text.ja,
                dose_quantity=parsed.get("dose_quantity"),
                dose_unit=parsed.get("dose_unit") or "",
                route=parsed.get("route") or "",
            )
        )
    return orders
