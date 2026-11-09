"""Inpatient hyperkalemia response (Issue #2981).

A resulted potassium at or above ``treat_threshold_mmol_l``
(``reference_data/hyperkalemia_response.yaml``) starts a hold on every drug in
``hold_classes`` (ACE inhibitors, ARBs, potassium-sparing diuretics) for the
rest of the stay and places the country's treatment order set (calcium,
insulin with dextrose, a potassium binder) as one-time doses.

Pure functions of the lab results — no randomness, so a stay whose potassium
never reaches the threshold is unchanged.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

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


@dataclass(frozen=True)
class PotassiumHold:
    """A hyperkalemia hold: doses scheduled at or after ``since`` are held."""

    since: datetime
    value: float

    @property
    def reason(self) -> str:
        """The MAR hold reason — the potassium value, written the same way in
        both languages (a lab abbreviation and a unit)."""
        return f"K {self.value:.1f} mmol/L"


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
) -> list[Order]:
    """The country's hyperkalemia order set for a potassium result: one-time
    doses ordered shortly after the result. ``continuing`` — the potassium was
    already at or above the threshold the day before: only the ``ongoing``
    entries (the potassium binder) are ordered again; calcium and insulin
    are given at the start of an episode."""
    ordered = (hold.since + timedelta(minutes=TREATMENT_ORDER_DELAY_MIN)).replace(second=0, microsecond=0)
    value = f"{hold.value:.1f}"
    orders: list[Order] = []
    for entry in hyperkalemia_rules().treatment.get(country_code(country), []):
        if continuing and not entry.ongoing:
            continue
        drug = get_drug(entry.drug_id)
        assert drug is not None  # validated at load
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
            )
        )
    return orders
