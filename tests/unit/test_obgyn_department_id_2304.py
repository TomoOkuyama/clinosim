"""Obstetrics and gynaecology has one department id (Issue #2304)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from clinosim.simulator.hospital_ops import resolve_department

pytestmark = pytest.mark.unit

_DISPLAY = yaml.safe_load(Path("clinosim/locale/shared/department_display.yaml").read_text(encoding="utf-8"))
_DISPLAY_KEYS = set((_DISPLAY.get("departments") or _DISPLAY).keys())


def test_outpatient_department_ids_have_a_display() -> None:
    src = Path("clinosim/simulator/outpatient_dept.py").read_text(encoding="utf-8")
    assert set(re.findall(r':\s*"([a-z_]+)"', src)) <= _DISPLAY_KEYS


def test_perinatal_department_has_a_display() -> None:
    data = yaml.safe_load(Path("clinosim/locale/shared/perinatal.yaml").read_text(encoding="utf-8"))
    depts = re.findall(r"department: \"?([a-z_]+)", yaml.safe_dump(data))
    assert depts and set(depts) <= _DISPLAY_KEYS


@pytest.mark.parametrize("config", ["hospital_operations", "hospital_large", "hospital_small"])
def test_obstetrics_rolls_up_in_every_bundled_hospital(config: str) -> None:
    ops = yaml.safe_load(Path(f"clinosim/config/{config}.yaml").read_text(encoding="utf-8"))
    assert resolve_department("obstetrics_gynecology", ops) == "primary_care"
