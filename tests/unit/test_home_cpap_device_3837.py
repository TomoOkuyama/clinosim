"""Issue #3837: a patient with obstructive sleep apnea on CPAP therapy has a
home CPAP device (SNOMED 702172008 "Home CPAP unit"), emitted as a Device and an
active DeviceUseStatement; the unit is not an ICU device and carries no
sampled infection risk."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.device.engine import load_devices_config, place_home_devices

pytestmark = pytest.mark.unit

_CFG = load_devices_config()


def _record(
    code: str = "G47.30", onset: date | None = date(2017, 3, 1), procedures: list | None = None
) -> SimpleNamespace:
    patient = SimpleNamespace(
        patient_id="POP-1",
        chronic_conditions=[SimpleNamespace(code=code, onset_date=onset)],
    )
    return SimpleNamespace(patient=patient, procedures=procedures or [], extensions={})


def test_osa_patient_gets_a_home_cpap_unit_from_the_onset() -> None:
    (dev,) = place_home_devices(_record(), _CFG)
    assert dev.device_type == "home_cpap" and dev.snomed_code == "702172008"
    assert dev.origin == "home" and dev.removal_date is None
    assert dev.placement_date == "2017-03-01"
    assert dev.device_id == "dev-POP-1-home-cpap"


def test_unit_is_placed_at_the_first_recorded_cpap_therapy_when_it_is_in_the_record() -> None:
    proc = SimpleNamespace(
        procedure_type="CPAP therapy",
        procedure_code_us="94660",
        start_datetime=datetime(2025, 8, 4, 9, 0),
        encounter_id="ENC-1",
    )
    (dev,) = place_home_devices(_record(procedures=[proc]), _CFG)
    assert dev.placement_date == "2025-08-04" and dev.encounter_id == "ENC-1"


def test_other_patients_get_no_cpap_unit() -> None:
    assert place_home_devices(_record(code="I10"), _CFG) == []


def test_osa_subtypes_are_covered() -> None:
    assert len(place_home_devices(_record(code="G47.33"), _CFG)) == 1


def test_home_unit_is_not_sampled_for_infection() -> None:
    from clinosim.modules.hai.enricher import _DEVICE_TO_HAI

    assert "home_cpap" not in _DEVICE_TO_HAI
