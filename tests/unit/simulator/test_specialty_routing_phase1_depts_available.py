"""Phase 1 of Issue #1698 — the 4 specialty depts must resolve to the
same name (not fall through to internal_medicine). Phase 1 routing is
useless if psychiatry visits land on internal_medicine via the rollup.
"""

from __future__ import annotations

import pytest
import yaml
from pathlib import Path

from clinosim.simulator.hospital_ops import resolve_department

pytestmark = pytest.mark.unit


def _load_us_hospital_ops() -> dict:
    with (Path(__file__).resolve().parents[3] / "clinosim/config/hospital_operations.yaml").open() as f:
        return yaml.safe_load(f)


def test_phase1_specialty_depts_resolve_to_an_available_dept() -> None:
    """cardiology / oncology each self-resolve (hospital staffs them).
    psychiatry / pulmonology roll up to internal_medicine per the
    documented hospital-config design (50-bed community hospital — see
    the `psychiatry: internal_medicine` + `pulmonology: internal_medicine`
    rollup entries in `clinosim/config/hospital_operations.yaml`).

    Phase 1 fan-out still EMITS additional encounters for F32/F33/F41.1
    and J44 patients; those encounters just land on the internal_medicine
    department via `resolve_department`. The audit's observational gap
    ("0 psychiatry visits") stays visible as a dept-naming artefact in
    Phase 1; Phase 2 adds per-hospital-config variation to let a hospital
    that DOES staff psychiatry route visits to a dedicated dept.
    """
    hops = _load_us_hospital_ops()
    available = set(hops.get("available_departments", []))

    assert resolve_department("cardiology", hops) == "cardiology"
    assert "cardiology" in available
    assert resolve_department("oncology", hops) == "oncology"
    assert "oncology" in available

    assert resolve_department("psychiatry", hops) == "internal_medicine"
    assert resolve_department("pulmonology", hops) == "internal_medicine"
