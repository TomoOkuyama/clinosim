"""Immunization.encounter linking to vaccination encounter (S1, #1184 F4 / #1186 F6).

Before the fix, 100% of `Immunization.encounter` slots were blank
because the scheduler-populated `ImmunizationRecord` carries no
encounter_id. This test asserts the emit-time bridge: when an
encounter on the same day has a vaccination-purpose chief_complaint,
`Immunization.encounter` references that encounter; otherwise it
stays absent (no fabrication).
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from clinosim.modules.output.fhir_r4.procedures.immunization import (
    _match_immunization_encounter,
)


def _imm(occ: date):
    return SimpleNamespace(vaccine_cvx="140", occurrence_date=occ)


def _enc(enc_id: str, adm: datetime, chief: str = "", chief_ja: str = ""):
    return SimpleNamespace(
        encounter_id=enc_id,
        admission_datetime=adm,
        chief_complaint=chief,
        chief_complaint_ja=chief_ja,
    )


def test_no_encounters_returns_empty() -> None:
    assert _match_immunization_encounter(_imm(date(2026, 8, 1)), []) == ""


def test_no_same_day_encounter_returns_empty() -> None:
    encs = [_enc("enc-1", datetime(2026, 7, 30, 10, 0), chief_ja="予防接種")]
    assert _match_immunization_encounter(_imm(date(2026, 8, 1)), encs) == ""


def test_same_day_vaccination_encounter_ja_matches() -> None:
    encs = [_enc("enc-1", datetime(2026, 8, 1, 10, 0), chief_ja="予防接種")]
    assert _match_immunization_encounter(_imm(date(2026, 8, 1)), encs) == "enc-1"


def test_same_day_english_vaccine_keyword_matches() -> None:
    encs = [_enc("enc-2", datetime(2026, 8, 1, 10, 0), chief="Vaccination")]
    assert _match_immunization_encounter(_imm(date(2026, 8, 1)), encs) == "enc-2"


def test_same_day_immunization_keyword_matches() -> None:
    encs = [_enc("enc-3", datetime(2026, 8, 1, 10, 0), chief="Immunization visit")]
    assert _match_immunization_encounter(_imm(date(2026, 8, 1)), encs) == "enc-3"


def test_same_day_non_vaccination_encounter_returns_empty() -> None:
    # Same day but chief complaint is not vaccination-related.
    encs = [_enc("enc-4", datetime(2026, 8, 1, 10, 0), chief="Annual health screening")]
    assert _match_immunization_encounter(_imm(date(2026, 8, 1)), encs) == ""


def test_first_matching_encounter_wins() -> None:
    encs = [
        _enc("enc-morning", datetime(2026, 8, 1, 9, 0), chief_ja="予防接種"),
        _enc("enc-afternoon", datetime(2026, 8, 1, 14, 0), chief_ja="予防接種"),
    ]
    assert _match_immunization_encounter(_imm(date(2026, 8, 1)), encs) == "enc-morning"
