"""The reason text of a JP Immunization names its program (Issue #3660)."""

from __future__ import annotations

import pytest

from clinosim.locale.i18n import t
from clinosim.modules.immunization.engine import load_schedule, vaccine_program
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.procedures.immunization import _bb_immunizations

pytestmark = pytest.mark.unit

_VOLUNTARY_JA = "予防接種（任意接種）"
_ROUTINE_JA = "予防接種（定期接種）"


def _reason(cvx: str, country: str, age: int, occurrence: str = "2025-11-10") -> str:
    born = f"{2025 - age}-01-01"
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
    return resource["reasonCode"][0]["text"]


def test_jp_influenza_is_voluntary_under_65_and_routine_from_65() -> None:
    assert _reason("150", "JP", 40) == _VOLUNTARY_JA
    assert _reason("150", "JP", 64) == _VOLUNTARY_JA
    assert _reason("150", "JP", 70) == _ROUTINE_JA
    assert _reason("150", "JP", 65) == _ROUTINE_JA


def test_jp_covid_follows_the_same_age_rule() -> None:
    assert _reason("309", "JP", 40) == _VOLUNTARY_JA
    assert _reason("309", "JP", 70) == _ROUTINE_JA


def test_jp_mumps_is_voluntary_at_any_age() -> None:
    assert _reason("07", "JP", 1, occurrence="2025-11-10") == _VOLUNTARY_JA


def test_jp_routine_childhood_and_elder_vaccines_stay_routine() -> None:
    assert _reason("19", "JP", 0, "2025-06-01") == _ROUTINE_JA  # BCG
    assert _reason("106", "JP", 0, "2025-06-01") == _ROUTINE_JA  # DPT-IPV
    assert _reason("33", "JP", 70) == _ROUTINE_JA  # PPSV23


def test_us_keeps_the_routine_phrase_for_every_vaccine() -> None:
    for cvx in ("150", "140", "115", "33"):
        assert _reason(cvx, "US", 40) == t("immunization_fhir.vaccination_routine", "en")


def test_every_jp_schedule_cvx_resolves_a_program() -> None:
    schedule = load_schedule("JP")
    assert schedule
    for name, vaccine in schedule.items():
        codes = {str(vaccine["cvx"])} | {str(p["cvx"]) for p in vaccine.get("products") or []}
        for cvx in codes:
            assert vaccine_program("JP", cvx, 40) in ("routine", "voluntary"), (name, cvx)


def test_the_voluntary_phrase_has_both_languages() -> None:
    assert t("immunization_fhir.vaccination_voluntary", "ja") == _VOLUNTARY_JA
    assert t("immunization_fhir.vaccination_voluntary", "en") == "Vaccination (voluntary)"
