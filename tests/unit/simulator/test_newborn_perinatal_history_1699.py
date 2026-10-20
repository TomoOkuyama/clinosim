"""Newborn perinatal codes land in perinatal_history, not chronic_conditions (Issue #1699).

Z38.0 (single liveborn admission dx), P07.x (preterm newborn), P22.0 (RDS),
P59.x (neonatal jaundice) are one-time perinatal-episode codes. They do not
persist as chronic conditions after the perinatal period and should not
drive the problem-list emit path.

L22 (diaper dermatitis) + L20.9 (atopic dermatitis) are first-year chronic
conditions and legitimately belong in chronic_conditions.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from clinosim.simulator.perinatal import _build_newborn_patient, _sample_newborn_conditions


class _FakeMother:
    def __init__(self, pid: str = "POP-TEST-M") -> None:
        self.patient_id = pid
        self.household_id = "HH"
        self.sex = "F"
        self.preferred_language = "en"
        self.insurance_type = "NHI_employee"
        self.address = type(
            "Addr", (), {"state": "", "city": "", "line1": "", "line2": "", "postal_code": "", "country": "US"}
        )()
        self.contact = type(
            "C",
            (),
            {
                "phone_home": "",
                "phone_mobile": "",
                "phone_primary": "",
                "email": "",
                "emergency_contact_name": "Alice Mother",
                "emergency_contact_phone": "",
                "emergency_contact_relationship": "",
            },
        )()
        self.name = type(
            "N",
            (),
            {
                "family_name": "Mother",
                "given_name": "Alice",
                "display_name": "Alice Mother",
                "name_script": "en",
                "phonetic": None,
            },
        )()


@pytest.mark.unit
def test_newborn_z38_not_in_chronic_conditions():
    """Z38.0 is the delivery encounter's admission/discharge dx (emitted via
    Encounter path). It must not appear in chronic_conditions where downstream
    FHIR emit would stamp it as an active indefinite problem-list item."""
    mother = _FakeMother()
    newborn = _build_newborn_patient(mother, delivery_date=datetime(2024, 6, 1).date(), sex="M", country="US")
    chronic_codes = {c.code for c in newborn.chronic_conditions}
    assert "Z38.0" not in chronic_codes, f"Z38.0 must not be in chronic_conditions; got {sorted(chronic_codes)}"


@pytest.mark.unit
def test_newborn_z38_moved_to_perinatal_history():
    """Z38.0 is still recorded on the newborn — in the new perinatal_history
    field — so downstream readers (narrative, audit) can see the birth lineage."""
    mother = _FakeMother()
    newborn = _build_newborn_patient(mother, delivery_date=datetime(2024, 6, 1).date(), sex="M", country="US")
    peri_codes = {c.code for c in newborn.perinatal_history}
    assert "Z38.0" in peri_codes, f"Z38.0 must appear in perinatal_history; got {sorted(peri_codes)}"


@pytest.mark.unit
def test_perinatal_p_codes_route_to_perinatal_history():
    """P07.x / P22.x / P59.x (perinatal/newborn chapter codes) must land in
    perinatal_history, not chronic_conditions. Verified via a rigged yaml
    that forces every perinatal code to fire."""
    rigged_cfg = {
        "newborn_conditions": [
            {"code": "P07.3", "probability": 1.0},
            {"code": "P59.9", "probability": 1.0},
            {"code": "P22.0", "probability": 1.0},
            {"code": "L22", "probability": 1.0},  # legitimately chronic
            {"code": "L20.9", "probability": 1.0},  # legitimately chronic
        ]
    }
    with patch("clinosim.simulator.perinatal.load_perinatal_config", return_value=rigged_cfg):
        persistent, perinatal = _sample_newborn_conditions("POP-X", datetime(2024, 6, 1).date())
    persistent_codes = {c.code for c in persistent}
    peri_codes = {c.code for c in perinatal}
    assert "P07.3" in peri_codes
    assert "P59.9" in peri_codes
    assert "P22.0" in peri_codes
    assert "L22" in persistent_codes
    assert "L20.9" in persistent_codes
    assert persistent_codes.isdisjoint(peri_codes)
