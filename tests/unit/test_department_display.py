"""Unit tests for FHIR department display resolution (DUP-1).

Guards against the silent-fallback bug where US Encounter.serviceType emitted a
raw snake_case department key (e.g. "primary_care") because the English display
table was missing entries. Department display is now sourced from the shared
locale/shared/department_display.yaml table for both EN and JA.
"""

import pytest

from clinosim.modules.output.fhir_r4_adapter import _build_encounter, _build_facility_bundle


def _service_text(enc: dict, country: str) -> str:
    resource = _build_encounter(enc, "patient-1", country=country)
    return resource["serviceType"]["text"]


@pytest.mark.unit
class TestEncounterServiceTypeDisplay:
    def test_us_primary_care_is_not_raw_key(self):
        # primary_care is an available_department in the default hospital config
        # but was missing from the EN display table -> raw key leaked to US output.
        text = _service_text({"department_id": "primary_care", "encounter_type": "ambulatory"}, "US")
        assert text == "Primary Care"

    def test_us_neurosurgery_is_not_raw_key(self):
        text = _service_text({"department_id": "neurosurgery", "encounter_type": "inpatient"}, "US")
        assert text == "Neurosurgery"

    def test_us_known_department_unchanged(self):
        text = _service_text({"department_id": "cardiology", "encounter_type": "inpatient"}, "US")
        assert text == "Cardiology"

    def test_jp_primary_care_unchanged(self):
        text = _service_text({"department_id": "primary_care", "encounter_type": "ambulatory"}, "JP")
        assert text == "総合診療科"

    def test_us_no_japanese_characters(self):
        # US output must be 100% English.
        for dept in ["primary_care", "neurosurgery", "psychiatry", "radiology", "pediatrics"]:
            text = _service_text({"department_id": dept, "encounter_type": "inpatient"}, "US")
            assert text.isascii(), f"{dept} -> {text!r} contains non-ASCII"


@pytest.mark.unit
class TestFacilityDepartmentDisplay:
    def _facility_dept_displays(self, country: str) -> dict[str, str]:
        config = {
            "available_departments": [
                "internal_medicine",
                "cardiology",
                "orthopedics",
                "primary_care",
            ],
            "wards": {},
            "resource_capacity": {"inpatient_beds": 50},
        }
        bundle = _build_facility_bundle(config, country)
        out = {}
        for entry in bundle["entry"]:
            res = entry["resource"]
            if res["resourceType"] == "Organization" and res["id"].startswith("dept-"):
                out[res["id"]] = res["name"]
        return out

    def test_us_facility_orthopedics_uses_canonical_name(self):
        displays = self._facility_dept_displays("US")
        assert displays["dept-orthopedics"] == "Orthopedic Surgery"

    def test_facility_matches_encounter_servicetype(self):
        # facility and encounter must agree on the same department's display.
        fac = self._facility_dept_displays("US")
        enc = _service_text({"department_id": "orthopedics", "encounter_type": "inpatient"}, "US")
        assert fac["dept-orthopedics"] == enc
