"""Per-code age limits live in one YAML (Issue #2286)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.eval.axes import clinical as eval_clinical
from clinosim.locale.loader import load_chronic_age_limits
from clinosim.simulator import inpatient

pytestmark = pytest.mark.unit


def test_yaml_holds_all_three_tables() -> None:
    limits = load_chronic_age_limits()
    assert limits["codes"]["E11"] == 20  # onset floor
    assert limits["implied_chronic_min_years"]["N18"] == 60  # inpatient implied-chronic gate
    assert "F00" in limits["adult_only_codes"]  # eval pediatric check


def test_consumers_read_the_yaml() -> None:
    limits = load_chronic_age_limits()
    assert inpatient._implied_chronic_min_age("N18") == limits["implied_chronic_min_years"]["N18"]
    assert inpatient._implied_chronic_min_age("E11.9") == limits["implied_chronic_min_years"]["E11"]
    assert eval_clinical._adult_only_internal_codes() == tuple(limits["adult_only_codes"])


def test_no_python_copies_remain() -> None:
    assert "_IMPLIED_CHRONIC_AGE_MIN = {" not in Path(inpatient.__file__).read_text(encoding="utf-8")
    assert "_ADULT_ONLY_INTERNAL_CODES: tuple" not in Path(eval_clinical.__file__).read_text(encoding="utf-8")
