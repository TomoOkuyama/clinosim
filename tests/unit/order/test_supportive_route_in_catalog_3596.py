"""A supportive line never becomes a drug order whose route the drug lacks (Issue #3596)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

import clinosim
from clinosim.codes.drugs import identify_drug, route_class
from clinosim.datafiles import load_data_yaml
from clinosim.modules.order.engine import place_admission_orders

pytestmark = pytest.mark.unit

_PROTOCOLS = sorted((Path(clinosim.__file__).parent / "modules/disease/reference_data").glob("*.yaml"))


@pytest.mark.parametrize("country", ["us", "jp"])
def test_no_supportive_drug_order_has_a_route_outside_the_catalog(country: str) -> None:
    bad: list[str] = []
    for path in _PROTOCOLS:
        protocol = load_data_yaml(path)
        if not (protocol.get("order_protocols") or {}).get("admission_orders", {}).get("supportive"):
            continue
        orders = place_admission_orders(
            protocol, "P1", "E1", datetime(2025, 3, 1, 9), country, np.random.default_rng(0)
        )
        for o in orders:
            if "-ADM-S" not in o.order_id or o.order_type.value != "medication":
                continue
            drug = identify_drug(o.display_name.split(": ", 1)[-1])
            if drug is None or not drug.yj_by_route:
                continue
            if route_class(o.route or "") not in drug.yj_by_route:
                bad.append(f"{path.stem}: {o.display_name} route={o.route} catalog={sorted(drug.yj_by_route)}")
    assert not bad, bad


@pytest.mark.parametrize("country", ["us", "jp"])
def test_drugs_section_pointer_is_not_an_order(country: str) -> None:
    protocol = {
        "order_protocols": {
            "admission_orders": {"supportive": [{"type": "antibiotic", "detail": "Antibiotic (see drugs section)"}]}
        }
    }
    orders = place_admission_orders(protocol, "P1", "E1", datetime(2025, 3, 1, 9), country, np.random.default_rng(0))
    assert not [o for o in orders if "-ADM-S" in o.order_id and o.order_type.value == "medication"]
