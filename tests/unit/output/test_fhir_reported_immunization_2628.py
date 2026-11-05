"""Issue #2628: a reported immunization names no hospital performer."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.procedures.immunization import _bb_immunizations

pytestmark = pytest.mark.unit


def _imm(primary: bool) -> dict:
    return {
        "vaccine_cvx": "115",
        "occurrence_date": "2005-06-01",
        "status": "completed",
        "primary_source": primary,
        "administered_by": "NS-EM-004",
        "lot_number": "L123",
    }


def _ctx(imms: list[dict], country: str = "US") -> BundleContext:
    return BundleContext(
        record={"immunizations": imms, "encounters": []},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="P1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="",
        patient_sex="",
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_a_reported_dose_has_no_hospital_performer_and_states_its_origin(country: str) -> None:
    [r] = _bb_immunizations(_ctx([_imm(False)], country))
    assert r["primarySource"] is False
    assert "performer" not in r
    [coding] = r["reportOrigin"]["coding"]
    assert (coding["system"], coding["code"]) == ("http://terminology.hl7.org/CodeSystem/immunization-origin", "record")


def test_a_dose_given_here_keeps_its_nurse() -> None:
    [r] = _bb_immunizations(_ctx([_imm(True)]))
    assert r["performer"] == [{"actor": {"reference": "Practitioner/NS-EM-004"}}]
    assert "reportOrigin" not in r
