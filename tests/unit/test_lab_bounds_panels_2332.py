"""Eval plausibility bounds and lab panels have one source each (Issue #2332)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.codes.ucum import ucum_code
from clinosim.eval.axes.clinical import _LAB_BOUNDS_BY_UNIT
from clinosim.locale.loader import load_code_mapping
from clinosim.modules.observation.engine import LAB_UNITS, PHYSIOLOGIC_LIMITS, lab_panel_components
from clinosim.modules.order.panel_grouping import load_panel_definitions

pytestmark = pytest.mark.unit


def test_eval_bound_equals_the_generator_limit_for_every_emitted_unit() -> None:
    loinc_of = load_code_mapping("lab", "US")
    checked = 0
    for lab, limits in PHYSIOLOGIC_LIMITS.items():
        loinc, unit = loinc_of.get(lab), LAB_UNITS.get(lab)
        if not loinc or not unit:
            continue
        assert _LAB_BOUNDS_BY_UNIT[loinc][unit] == tuple(limits), lab
        assert _LAB_BOUNDS_BY_UNIT[loinc][ucum_code(unit)] == tuple(limits), lab
        checked += 1
    assert checked >= 20


def test_one_panel_definition() -> None:
    root = Path(__file__).resolve().parents[2] / "clinosim" / "modules"
    assert not (root / "order" / "reference_data" / "lab_panel_groups.yaml").exists()
    for name, panel in load_panel_definitions().items():
        assert lab_panel_components(name) == panel["components"]
