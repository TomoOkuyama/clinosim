"""Unit tests for panel-aware Order generation (PR1)."""

from datetime import datetime

import numpy as np

from clinosim.modules.order.engine import place_admission_orders, place_daily_lab_orders
from clinosim.types.encounter import OrderType


def _make_protocol(test_names: list[str]) -> dict:
    """Build a minimal disease protocol with the given lab tests."""
    return {
        "order_protocols": {
            "admission_orders": {
                "labs": [{"test": name, "code_loinc": "X"} for name in test_names],
            }
        },
        "drugs": {"first_line": {"us": []}},
    }


def test_admission_cbc_panel_orders_share_panel_key_and_datetime():
    """4 CBC components → 4 Orders with panel_key='CBC' and identical ordered_datetime."""
    protocol = _make_protocol(["WBC", "Hb", "Hct", "Plt"])
    rng = np.random.default_rng(42)
    base_time = datetime(2026, 6, 29, 8, 0)
    orders = place_admission_orders(
        protocol=protocol,
        patient_id="pt001",
        encounter_id="enc001",
        admission_time=base_time,
        country="us",
        rng=rng,
        ordered_by="doc1",
    )
    lab_orders = [o for o in orders if o.order_type == OrderType.LAB]
    assert len(lab_orders) == 4
    panel_keys = {o.panel_key for o in lab_orders}
    assert panel_keys == {"CBC"}
    datetimes = {o.ordered_datetime for o in lab_orders}
    assert len(datetimes) == 1, "panel members must share ordered_datetime"


def test_admission_standalone_tests_have_empty_panel_key():
    """Tests not forming a panel → panel_key='', independent datetimes."""
    protocol = _make_protocol(["Troponin_I", "BNP"])  # neither forms a panel
    rng = np.random.default_rng(42)
    base_time = datetime(2026, 6, 29, 8, 0)
    orders = place_admission_orders(
        protocol=protocol,
        patient_id="pt001",
        encounter_id="enc001",
        admission_time=base_time,
        country="us",
        rng=rng,
        ordered_by="doc1",
    )
    lab_orders = [o for o in orders if o.order_type == OrderType.LAB]
    assert len(lab_orders) == 2
    for o in lab_orders:
        assert o.panel_key == ""
    # Stand-alone orders have independent rng.normal draws → distinct datetimes.
    assert len({o.ordered_datetime for o in lab_orders}) == len(lab_orders)


def test_admission_mixed_panel_and_standalone():
    """4 CBC + 1 Troponin → 4 panel + 1 stand-alone."""
    protocol = _make_protocol(["WBC", "Hb", "Hct", "Plt", "Troponin_I"])
    rng = np.random.default_rng(42)
    base_time = datetime(2026, 6, 29, 8, 0)
    orders = place_admission_orders(
        protocol=protocol,
        patient_id="pt001",
        encounter_id="enc001",
        admission_time=base_time,
        country="us",
        rng=rng,
        ordered_by="doc1",
    )
    lab_orders = [o for o in orders if o.order_type == OrderType.LAB]
    panel_orders = [o for o in lab_orders if o.panel_key == "CBC"]
    standalone = [o for o in lab_orders if o.panel_key == ""]
    assert len(panel_orders) == 4
    assert len(standalone) == 1
    assert standalone[0].display_name == "Troponin_I"


def test_admission_below_min_components_falls_standalone():
    """2 CBC components < min_components=3 → both stand-alone."""
    protocol = _make_protocol(["WBC", "Plt"])
    rng = np.random.default_rng(42)
    base_time = datetime(2026, 6, 29, 8, 0)
    orders = place_admission_orders(
        protocol=protocol,
        patient_id="pt001",
        encounter_id="enc001",
        admission_time=base_time,
        country="us",
        rng=rng,
        ordered_by="doc1",
    )
    lab_orders = [o for o in orders if o.order_type == OrderType.LAB]
    assert len(lab_orders) == 2
    for o in lab_orders:
        assert o.panel_key == ""


def test_deterministic_panel_ordering():
    """Same seed → same Orders (panel iteration uses sorted keys)."""
    protocol = _make_protocol(["WBC", "Hb", "Hct", "Plt", "AST", "ALT", "ALP",
                               "T_Bil", "Albumin"])  # CBC + LFT
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    base_time = datetime(2026, 6, 29, 8, 0)
    orders1 = place_admission_orders(
        protocol=protocol, patient_id="pt001", encounter_id="enc001",
        admission_time=base_time, country="us", rng=rng1, ordered_by="doc1",
    )
    orders2 = place_admission_orders(
        protocol=protocol, patient_id="pt001", encounter_id="enc001",
        admission_time=base_time, country="us", rng=rng2, ordered_by="doc1",
    )
    assert [(o.order_id, o.panel_key, o.ordered_datetime) for o in orders1] == \
           [(o.order_id, o.panel_key, o.ordered_datetime) for o in orders2]


def test_daily_lab_panel_orders_share_panel_key_and_datetime():
    """When daily monitoring YAML has 4 CBC components, they form a CBC panel
    sharing panel_key and ordered_datetime (all emitted at morning order_time)."""
    protocol = {
        "order_protocols": {
            "daily_monitoring": {
                "labs": [
                    {"test": "WBC", "frequency": "daily"},
                    {"test": "Hb", "frequency": "daily"},
                    {"test": "Hct", "frequency": "daily"},
                    {"test": "Plt", "frequency": "daily"},
                ]
            }
        }
    }
    rng = np.random.default_rng(42)
    order_time = datetime(2026, 6, 30, 8, 0)
    orders = place_daily_lab_orders(
        protocol=protocol,
        patient_id="pt001",
        encounter_id="enc001",
        day_number=3,
        order_time=order_time,
        lab_frequency_multiplier=1.0,
        rng=rng,
        ordered_by="doc1",
    )
    lab_orders = [o for o in orders if o.order_type == OrderType.LAB]
    assert len(lab_orders) == 4
    assert {o.panel_key for o in lab_orders} == {"CBC"}
    # All 4 share the SAME ordered_datetime (panel uses morning order_time directly).
    assert len({o.ordered_datetime for o in lab_orders}) == 1


def test_daily_lab_standalone_tests_have_empty_panel_key():
    """Typical daily monitoring tests that don't meet any panel's min_components
    are emitted as stand-alone Orders with panel_key=''."""
    protocol = {
        "order_protocols": {
            "daily_monitoring": {
                "labs": [
                    {"test": "CRP", "frequency": "daily"},
                    {"test": "Creatinine", "frequency": "daily"},
                ]
            }
        }
    }
    rng = np.random.default_rng(42)
    order_time = datetime(2026, 6, 30, 8, 0)
    orders = place_daily_lab_orders(
        protocol=protocol,
        patient_id="pt001",
        encounter_id="enc001",
        day_number=1,
        order_time=order_time,
        lab_frequency_multiplier=1.0,
        rng=rng,
        ordered_by="doc1",
    )
    lab_orders = [o for o in orders if o.order_type == OrderType.LAB]
    assert len(lab_orders) == 2
    assert all(o.panel_key == "" for o in lab_orders)
