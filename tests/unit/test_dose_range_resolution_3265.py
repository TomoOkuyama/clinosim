"""A protocol dose range is resolved to one dose (Issue #3265)."""

from __future__ import annotations

import re
from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.disease.protocol import load_all_disease_protocols, load_disease_protocol
from clinosim.modules.order.dose_range import resolve_dose_ranges
from clinosim.modules.order.engine import place_admission_orders

pytestmark = pytest.mark.unit

_DOSE_RANGE = re.compile(
    r"(?<![\d.])\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*(?:mcg|mg|ug|mEq|mL|IU|units?|U|g|L)(?![A-Za-z/])"
)


@pytest.mark.parametrize(
    ("written", "resolved"),
    [
        ("25-100mg PO daily", "25mg PO daily"),
        ("15-20mg/kg IV q12h (trough 15-20)", "15mg/kg IV q12h (trough 15-20)"),
        ("NS 80-125 mL/h", "NS 125 mL/h"),
        ("10mg IV bolus, then 5-15mg/h drip", "10mg IV bolus, then 5mg/h drip"),
        ("Initial 2-5mg PO daily, target INR 1.5-2.5", "Initial 2mg PO daily, target INR 1.5-2.5"),
        ("NS 150-200 mL/h, target UOP > 1-1.5 mL/kg/h", "NS 200 mL/h, target UOP > 1-1.5 mL/kg/h"),
        ("30-40mg PO daily x5-7 days", "30mg PO daily x5-7 days"),
        ("500mg PO BID", "500mg PO BID"),
    ],
)
def test_a_range_resolves_to_one_dose(written: str, resolved: str) -> None:
    assert resolve_dose_ranges(written) == resolved


def test_no_loaded_protocol_dose_or_detail_is_a_range() -> None:
    bad = []
    for disease_id, protocol in load_all_disease_protocols().items():

        def walk(node: object, path: str) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in ("dose", "detail") and isinstance(v, str) and _DOSE_RANGE.search(v):
                        bad.append((disease_id, path, v))
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        walk(protocol.model_dump(), "")
    assert not bad, bad[:5]


def test_the_written_range_is_kept_as_titration_metadata() -> None:
    entries = load_disease_protocol("atrial_fibrillation_rvr").drugs["discharge_oral"]["us"]
    metoprolol = next(e for e in entries if e.get("drug_id") == "metoprolol_succinate" or "25mg" in str(e.get("dose")))
    assert metoprolol["dose"].startswith("25mg")
    assert metoprolol["titration_range"].startswith("25-100mg")


def test_an_iv_fluid_order_is_named_by_one_rate() -> None:
    protocol = load_disease_protocol("bacterial_pneumonia").model_dump()
    orders = place_admission_orders(
        protocol, "P1", "ENC1", datetime(2026, 1, 1, 8), "US", np.random.default_rng(1), patient_weight_kg=70.0
    )
    fluids = [o for o in orders if (o.display_name or "").startswith("IV_fluid")]
    assert fluids
    assert all("-" not in o.display_name for o in fluids)
    assert fluids[0].dose_quantity == 125.0
    assert "125 mL/h" in fluids[0].display_name


def test_no_discharge_oral_entry_is_open_ended() -> None:
    """Every discharge_oral entry states a supply in days: the 28-day renewal
    supply of a maintenance drug, never 0 or "ongoing"."""
    bad = []
    for disease_id, protocol in load_all_disease_protocols().items():
        block = protocol.drugs.get("discharge_oral")
        if not isinstance(block, dict):
            continue
        for key in ("japan", "us"):
            entries = block.get(key) or []
            for e in [entries] if isinstance(entries, dict) else entries:
                if (
                    isinstance(e, dict)
                    and "duration_days" in e
                    and not (isinstance(e["duration_days"], int) and e["duration_days"] > 0)
                ):
                    bad.append((disease_id, key, e.get("drug_id"), e["duration_days"]))
    assert not bad, bad
