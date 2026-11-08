"""Issue #2823: HAI antibiotic doses name the giving nurse of the encounter's
ward, picked stably by the order (no RNG)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.antibiotic.enricher import enrich_antibiotic
from clinosim.types.hai import HAIEvent
from clinosim.types.staff import StaffMember, StaffRoster

pytestmark = pytest.mark.unit


def _roster() -> StaffRoster:
    def nurse(i: str, ward: str) -> StaffMember:
        return StaffMember(staff_id=f"NS-{i}", name=i, role="nurse", department="internal_medicine", ward=ward)

    return StaffRoster(members=[nurse("A1", "W1"), nurse("A2", "W1"), nurse("B1", "W2")])


def _run(hai_type: str) -> list:
    ev = HAIEvent(
        hai_id="h1",
        encounter_id="enc-1",
        hai_type=hai_type,
        source_device_id="d1",
        icd10_code="",
        snomed_code="",
        onset_date="2026-01-10",
        organism_snomed="",
        culture_specimen_id="",
    )
    rec = SimpleNamespace(
        patient=SimpleNamespace(patient_id="p1"),
        encounters=[{"encounter_id": "enc-1", "ward_id": "W1", "department_id": "internal_medicine"}],
        orders=[],
        medication_administrations=[],
        microbiology=[],
        extensions={"hai": [ev]},
    )
    cfg = SimpleNamespace(country="US", snapshot_date=None, time_range=("2026-01-01", "2026-12-31"))
    enrich_antibiotic(SimpleNamespace(config=cfg, master_seed=42, records=[rec], roster=_roster()))
    return rec.medication_administrations


@pytest.mark.parametrize("hai_type", ["cauti", "clabsi"])
def test_every_hai_dose_names_a_nurse_of_the_ward(hai_type: str) -> None:
    mars = _run(hai_type)
    assert mars
    assert {m.administered_by for m in mars} <= {"NS-A1", "NS-A2"}


def test_one_order_keeps_one_nurse() -> None:
    mars = _run("cauti")
    assert len({m.administered_by for m in mars}) == 1
