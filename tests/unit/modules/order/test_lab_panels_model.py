"""The lab_panels.yaml model rejects every malformed shape (Issue #2569)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from clinosim.datafiles import load_data_yaml
from clinosim.modules.order.panel_grouping import _PANEL_YAML, LabPanels

pytestmark = pytest.mark.unit


def _shipped() -> dict[str, Any]:
    return copy.deepcopy(load_data_yaml(_PANEL_YAML))


def _reordered(d: dict[str, Any]) -> None:
    d["panels"] = dict(reversed(list(d["panels"].items())))


def test_shipped_yaml_is_accepted() -> None:
    LabPanels.model_validate(_shipped())


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (lambda d: d.clear(), "panels section is empty"),
        (lambda d: d.update({"panels": {}}), "panels section is empty"),
        (lambda d: d["panels"].pop("CBC"), "missing panels declared in PANEL_PRIORITY_ORDER"),
        (lambda d: d["panels"].update({"Extra": d["panels"]["CBC"]}), "NOT in PANEL_PRIORITY_ORDER"),
        (_reordered, "does not match PANEL_PRIORITY_ORDER"),
        (lambda d: d["panels"]["CBC"].pop("loinc"), "loinc"),
        (lambda d: d["panels"]["CBC"].pop("display"), "display"),
        (lambda d: d["panels"]["CBC"].update({"display": {"ja": "血算"}}), "empty display string"),
        (lambda d: d["panels"]["CBC"].update({"components": []}), "components"),
        (lambda d: d["panels"]["CBC"].update({"components": "WBC"}), "components"),
        (lambda d: d["panels"]["CBC"].pop("min_components"), "min_components"),
        (lambda d: d["panels"]["CBC"].update({"min_components": 0}), "min_components"),
        (lambda d: d["panels"]["CBC"].update({"min_components": "3"}), "min_components"),
        (lambda d: d["panels"]["CBC"].update({"loinc": "99999-9"}), "unknown LOINC code '99999-9'"),
    ],
)
def test_rejections(break_it: Callable[[dict[str, Any]], Any], message: str) -> None:
    data = _shipped()
    break_it(data)
    with pytest.raises(ValueError, match=message):
        LabPanels.model_validate(data)
