"""Issue #2641: deliveries and newborns are admitted to a maternity ward and a nursery."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import yaml

from clinosim import determinism
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.hospital_ops import validate_hospital_ops
from clinosim.simulator.perinatal import simulate_delivery_encounter
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_CONFIGS = ("hospital_operations", "hospital_small", "hospital_large")


def _load(name: str) -> dict:
    path = Path(__file__).resolve().parents[3] / "clinosim" / "config" / f"{name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", _CONFIGS)
def test_every_hospital_has_a_maternity_ward_and_a_nursery(name: str) -> None:
    ops = _load(name)
    validate_hospital_ops(ops, name)
    assert "obstetrics_gynecology" in ops["available_departments"]
    assert "obstetrics_gynecology" not in ops["department_rollup"]
    perinatal = ops["perinatal_wards"]
    for ward in (perinatal["maternity"], perinatal["nursery"]):
        assert ward in ops["wards"]["obstetrics_gynecology"]
        assert ops["ward_capacity"][ward] > 0


@pytest.mark.parametrize("name", _CONFIGS)
def test_the_existing_staff_are_unchanged(name: str) -> None:
    """Obstetric staff are generated after everyone else, so no earlier draw moves."""
    ops = _load(name)
    without = dict(ops, available_departments=[d for d in ops["available_departments"] if d != "obstetrics_gynecology"])
    without["wards"] = {d: w for d, w in ops["wards"].items() if d != "obstetrics_gynecology"}
    before = generate_roster(ops["hospital_scale"], "US", determinism.default_rng(7), hospital_config=without)
    after = generate_roster(ops["hospital_scale"], "US", determinism.default_rng(7), hospital_config=ops)
    n = len(before.members)
    assert [(m.staff_id, m.name) for m in after.members[:n]] == [(m.staff_id, m.name) for m in before.members]
    added = after.members[n:]
    assert any(m.role == "physician" and m.department == "obstetrics_gynecology" for m in added)
    wards = {m.ward for m in added if m.role == "nurse"}
    assert {ops["perinatal_wards"]["maternity"], ops["perinatal_wards"]["nursery"]} <= wards


def test_the_mother_and_the_newborn_get_a_ward_and_a_bed() -> None:
    ops = _load("hospital_operations")
    roster = generate_roster(ops["hospital_scale"], "JP", determinism.default_rng(1), hospital_config=ops)
    records = simulate_delivery_encounter(
        patient=PatientProfile(patient_id="POP-000001", sex="F", age=28),
        visit_date=datetime(2024, 7, 15, 10, 0),
        roster=roster,
        rng=np.random.default_rng(42),
        country="JP",
        hospital_ops=ops,
    )
    mother, newborn = records[0].encounters[0], records[1].encounters[0]
    assert mother.department_id == newborn.department_id == "obstetrics_gynecology"
    assert mother.ward_id == ops["perinatal_wards"]["maternity"]
    assert newborn.ward_id == ops["perinatal_wards"]["nursery"]
    for enc in (mother, newborn):
        ward, bed = enc.bed_number.rsplit("-", 1)
        assert ward == enc.ward_id and 1 <= int(bed) <= ops["ward_capacity"][enc.ward_id]
    attending = next(m for m in roster.members if m.staff_id == mother.attending_physician_id)
    assert attending.department == "obstetrics_gynecology"
