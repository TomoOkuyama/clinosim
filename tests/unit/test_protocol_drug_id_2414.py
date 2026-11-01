"""Protocol drug lists are read by drug_id (Issue #2414)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

import clinosim
from clinosim.codes.drugs import drug_ref, get_drug, protocol_drug_name
from clinosim.modules.order.engine import protocol_drug_order_code

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent


def test_protocol_drug_name() -> None:
    assert protocol_drug_name({"drug_id": "ceftriaxone"}) == get_drug("ceftriaxone").names["en"]
    assert protocol_drug_name({"drug": "Hemodialysis"}) == "Hemodialysis"
    assert protocol_drug_name({}) == ""


@pytest.mark.parametrize("country", ["US", "JP"])
def test_drug_id_entry_gives_the_same_order_code(country: str) -> None:
    by_name = {"drug": "Ceftriaxone", "dose": "1g IV q24h"}
    by_id = {"drug_id": "ceftriaxone", "dose": "1g IV q24h"}
    assert protocol_drug_order_code(by_id, country) == protocol_drug_order_code(by_name, country)


def test_admission_order_from_a_drug_id_entry() -> None:
    from clinosim.modules.order.engine import place_admission_orders

    protocol = {"drugs": {"first_line": {"us": [{"drug_id": "ceftriaxone", "dose": "1g IV q24h"}]}}}
    orders = place_admission_orders(protocol, "P1", "E1", datetime(2025, 3, 1, 9), "us", np.random.default_rng(0))
    meds = [o for o in orders if o.order_type.value == "medication"]
    cef = [o for o in meds if o.display_name == "Ceftriaxone"]
    assert len(cef) == 1
    assert cef[0].order_code_system == "rxnorm"


def test_no_drug_name_that_is_exactly_a_catalog_name() -> None:
    """Every protocol entry whose name is a catalog drug's English name uses
    drug_id; the remaining names are variants or uncatalogued (#2415)."""
    hits: list[str] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            name = x.get("drug")
            if isinstance(name, str):
                rec = get_drug(drug_ref(name))
                if rec is not None and rec.names["en"] == name:
                    hits.append(name)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for path in (_ROOT / "modules/disease/reference_data").glob("*.yaml"):
        walk(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert not hits, sorted(set(hits))
