"""Each vaccine is charted with its own route, site and dose (Issue #3005)."""

from __future__ import annotations

import pytest

from clinosim.modules.immunization.engine import load_schedule
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.procedures.immunization import _bb_immunizations

pytestmark = pytest.mark.unit

_ORAL, _PERCUTANEOUS, _SC, _IM = "26643006", "428191002", "34206005", "78421000"
_LEFT_THIGH, _LEFT_UPPER_ARM = "61396006", "368208006"


def _emit(cvx: str, country: str, occurrence: str = "2025-06-01", born: str = "2025-01-01") -> dict:
    ctx = BundleContext(
        record={"immunizations": [{"vaccine_cvx": cvx, "occurrence_date": occurrence, "status": "completed"}]},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"date_of_birth": born},
        patient_id="P1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="",
        patient_sex="",
    )
    (resource,) = _bb_immunizations(ctx)
    return resource


def _code(concept: dict) -> str:
    return concept["coding"][0]["code"]


def test_rotarix_is_oral_with_1_5_ml() -> None:
    r = _emit("119", "JP")
    assert _code(r["route"]) == _ORAL
    assert r["doseQuantity"]["value"] == 1.5
    assert "site" not in r


def test_rotateq_is_oral_with_2_ml() -> None:
    r = _emit("116", "US")
    assert _code(r["route"]) == _ORAL and r["doseQuantity"]["value"] == 2.0


def test_bcg_is_percutaneous_in_the_upper_arm() -> None:
    r = _emit("19", "JP")
    assert _code(r["route"]) == _PERCUTANEOUS
    assert _code(r["site"]) == _LEFT_UPPER_ARM
    assert "doseQuantity" not in r


def test_an_infant_im_dose_goes_into_the_thigh() -> None:
    r = _emit("20", "US")  # DTaP at 5 months
    assert _code(r["route"]) == _IM and _code(r["site"]) == _LEFT_THIGH


def test_an_adult_im_dose_goes_into_the_upper_arm() -> None:
    r = _emit("150", "US", occurrence="2025-10-01", born="1960-01-01")
    assert _code(r["route"]) == _IM and _code(r["site"]) == _LEFT_UPPER_ARM


def test_jp_inactivated_vaccines_are_subcutaneous_in_the_upper_arm() -> None:
    r = _emit("106", "JP")  # DTaP-IPV at 5 months
    assert _code(r["route"]) == _SC and _code(r["site"]) == _LEFT_UPPER_ARM


def test_jp_je_dose_depends_on_age() -> None:
    assert _emit("129", "JP", occurrence="2027-06-01", born="2025-01-01")["doseQuantity"]["value"] == 0.25
    assert _emit("129", "JP", occurrence="2029-06-01", born="2025-01-01")["doseQuantity"]["value"] == 0.5


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_vaccine_states_its_route(country: str) -> None:
    for name, vaccine in load_schedule(country).items():
        assert (vaccine.get("administration") or {}).get("route"), name
