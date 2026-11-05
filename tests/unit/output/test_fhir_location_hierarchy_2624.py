"""Issue #2624: every ward, area and room Location is placed in the hospital."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.encounters.facility import _build_facility_bundle

pytestmark = pytest.mark.unit

_CONFIG = {
    "available_departments": ["emergency_medicine", "primary_care", "general_surgery", "internal_medicine"],
    "wards": {"emergency_medicine": ["ER"], "primary_care": ["OPD"], "internal_medicine": ["4A"]},
    "ward_capacity": {"4A": 2},
    "resource_capacity": {"inpatient_beds": 50, "operating_rooms": 2},
}


def _locations(country: str) -> dict[str, dict]:
    return {
        e["resource"]["id"]: e["resource"]
        for e in _build_facility_bundle(_CONFIG, country)["entry"]
        if e["resource"]["resourceType"] == "Location"
    }


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_ward_area_and_room_is_part_of_the_hospital(country: str) -> None:
    locations = _locations(country)
    placed = [loc for loc in locations.values() if loc["physicalType"]["coding"][0]["code"] in ("wa", "area", "ro")]
    assert placed
    for loc in placed:
        assert loc.get("partOf") == {"reference": "Location/loc-hospital-main"}, loc["id"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_a_bed_stays_part_of_its_ward_and_every_parent_exists(country: str) -> None:
    locations = _locations(country)
    assert locations["loc-bed-4A-01"]["partOf"] == {"reference": "Location/loc-ward-4A"}
    for loc in locations.values():
        if "partOf" in loc:
            assert loc["partOf"]["reference"].split("/")[1] in locations
