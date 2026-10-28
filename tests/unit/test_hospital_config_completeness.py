"""Hospital configs are complete and self-consistent (Issue #2128)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.simulator._setup import _load_hospital_ops
from clinosim.simulator.hospital_ops import pick_ward, resolve_department, validate_hospital_ops

pytestmark = pytest.mark.unit

_CONFIGS = sorted(Path("clinosim/config").glob("hospital_*.yaml"))
_EXPECTED_SCALE = {"hospital_small.yaml": "small", "hospital_operations.yaml": "medium", "hospital_large.yaml": "large"}


@pytest.mark.parametrize("path", _CONFIGS, ids=lambda p: p.name)
def test_shipped_config_is_complete(path: Path) -> None:
    ops = _load_hospital_ops(str(path))
    assert ops["hospital_scale"] == _EXPECTED_SCALE[path.name]
    beds = ops["resource_capacity"]["inpatient_beds"]
    assert sum(ops["ward_capacity"].values()) == beds


def test_large_hospital_has_its_own_wards_and_specialties() -> None:
    ops = _load_hospital_ops("clinosim/config/hospital_large.yaml")
    for dept in ("pulmonology", "neurology", "nephrology", "neurosurgery", "psychiatry"):
        assert resolve_department(dept, ops) == dept
    assert pick_ward("neurology", ops, None) not in ("4E", "4W")
    assert ops["resource_capacity"]["inpatient_beds"] == 200


def test_incomplete_config_fails_loudly(tmp_path: Path) -> None:
    good = yaml.safe_load(Path("clinosim/config/hospital_large.yaml").read_text())
    missing = {k: v for k, v in good.items() if k != "wards"}
    with pytest.raises(ValueError, match="wards"):
        validate_hospital_ops(missing, "test")
    bad_sum = {**good, "ward_capacity": {**good["ward_capacity"], "4E": good["ward_capacity"]["4E"] + 5}}
    with pytest.raises(ValueError, match="200"):
        validate_hospital_ops(bad_sum, "test")
    stray = {**good, "wards": {**good["wards"], "cardiology": ["5E", "9Z"]}}
    with pytest.raises(ValueError, match="9Z"):
        validate_hospital_ops(stray, "test")
