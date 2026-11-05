"""Every lab a protocol orders resolves to a coded lab (Issue #2583)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from clinosim.locale.loader import load_code_mapping
from clinosim.modules.observation.engine import canonical_lab_name
from clinosim.modules.observation.order_routing import OrderRouting, OrderTarget, lab_order_targets
from clinosim.modules.order.panel_grouping import load_panel_definitions
from clinosim.types.encounter import OrderType

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[4] / "clinosim"
_PROTOCOL_FILES = [
    *sorted((_ROOT / "modules/disease/reference_data").glob("*.yaml")),
    *sorted((_ROOT / "modules/encounter/reference_data").glob("*.yaml")),
    _ROOT / "locale/shared/chronic_followup.yaml",
]
_MONITORING_FILE = _ROOT / "locale/shared/chronic_medications.yaml"


def _lab_list_entries(node: Any, key: str = "") -> list[str]:
    """Names listed under any ``*lab*`` key (``labs``, ``add_labs``, ``additional_labs``, ...)."""
    names: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            names += _lab_list_entries(v, str(k))
    elif isinstance(node, list):
        if "lab" in key.lower():
            for item in node:
                name = item.get("test") if isinstance(item, dict) else item
                if isinstance(name, str):
                    names.append(name)
        for item in node:
            names += _lab_list_entries(item, key)
    return names


def _monitoring_entries(node: Any) -> list[str]:
    if isinstance(node, dict):
        own = [node["test"]] if isinstance(node.get("test"), str) else []
        return own + [n for v in node.values() for n in _monitoring_entries(v)]
    if isinstance(node, list):
        return [n for v in node for n in _monitoring_entries(v)]
    return []


def _ordered_names() -> set[str]:
    names = {n for f in _PROTOCOL_FILES for n in _lab_list_entries(yaml.safe_load(f.read_text()))}
    return names | set(_monitoring_entries(yaml.safe_load(_MONITORING_FILE.read_text())))


def test_every_ordered_lab_resolves_to_a_us_code_or_a_panel() -> None:
    us = load_code_mapping("lab", "US")
    panels = load_panel_definitions()
    uncoded = sorted(
        f"{name} -> {target.name}"
        for name in _ordered_names()
        for target in lab_order_targets(name)
        if target.order_type == OrderType.LAB and canonical_lab_name(target.name) not in us | panels
    )
    assert not uncoded


def test_routing_examples() -> None:
    assert lab_order_targets("SpO2") == ()
    assert lab_order_targets("Tetanus_status") == ()
    assert lab_order_targets("Chest_Xray") == (OrderTarget("Chest_Xray", OrderType.IMAGING),)
    assert [t.name for t in lab_order_targets("DIC_panel")] == ["PT", "PT_INR", "APTT", "Fibrinogen", "D_dimer", "Plt"]
    assert lab_order_targets("K_stat") == (OrderTarget("K_stat", OrderType.LAB),)
    assert canonical_lab_name("K_stat") == "K"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"vital_signs": ["X"], "history": [], "imaging": {"X": "Y"}, "expansions": {}}, "more than one section"),
        ({"vital_signs": [], "history": [], "imaging": {}, "expansions": {"G": []}}, "no components"),
        ({"vital_signs": [], "history": [], "imaging": {}, "expansions": {"G": ["No_such_lab"]}}, "No_such_lab"),
    ],
)
def test_routing_model_rejects(data: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        OrderRouting.model_validate(data)
