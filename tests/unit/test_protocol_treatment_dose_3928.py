"""Every drug-naming ``treatment`` entry of an encounter protocol carries a dose (Issue #3928).

A single-dose ED / clinic order read only ``IV ONCE`` when the protocol named the drug without
an amount (saline without a volume, a toxoid without 0.5 mL).
"""

import pytest

from clinosim.modules.encounter.protocol import load_all_encounter_conditions, load_encounter_condition
from clinosim.modules.order.engine import enrich_medication_order, parse_dose_string
from clinosim.modules.order.treatment_classifier import classify_encounter_treatment
from clinosim.types.encounter import Order, OrderType

pytestmark = pytest.mark.unit


def _drug_names(entry: dict) -> set[str]:
    return {str(entry.get("name", "")), *(str(v) for v in (entry.get("locale_name") or {}).values())} - {""}


def test_every_drug_treatment_entry_carries_a_dose_and_a_route() -> None:
    missing = []
    for cid, data in load_all_encounter_conditions().items():
        for tx in data.get("treatment") or []:
            if tx.get("dose") or tx.get("drug_id"):
                continue  # screening-visit sedation: dose stated in its own field
            for name in _drug_names(tx):
                if classify_encounter_treatment(name) != OrderType.MEDICATION:
                    continue
                if parse_dose_string(name).get("dose_quantity") is None or not (
                    tx.get("route") or parse_dose_string(name).get("route")
                ):
                    missing.append(f"{cid}: {name}")
    assert not missing, f"treatment entries without a dose or route: {sorted(missing)}"


@pytest.mark.parametrize("condition", ["vertigo", "eye_foreign_body", "flu_vaccination"])
def test_ed_treatment_resolves_to_an_order_with_a_dose(condition: str) -> None:
    for tx in load_encounter_condition(condition)["treatment"]:
        name = str(tx["name"])
        if classify_encounter_treatment(name) != OrderType.MEDICATION:
            continue
        order = enrich_medication_order(
            Order(order_id="o", patient_id="p", display_name=name, route=tx.get("route", ""))
        )
        assert order.dose_quantity is not None and order.dose_unit, name
