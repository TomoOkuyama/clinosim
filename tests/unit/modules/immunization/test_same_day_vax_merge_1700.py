"""Same-day vaccinations merge into one encounter (Issue #1700).

Multi-vaccine well-child visits (ACIP 2mo/4mo/6mo/12-15mo schedules give
3-5 vaccines simultaneously) must emit ONE encounter with multiple
Immunization resources — not one encounter per vaccine.

Merge key: (patient_id, occurrence_date). All CVX administered on the
same calendar day at the same patient's primary care visit collapse to
one Encounter via a shared synthesized encounter_id.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from clinosim.modules.immunization.enricher import _synthesize_vaccination_encounter


def _imm(occurrence_date: date, cvx: str) -> SimpleNamespace:
    return SimpleNamespace(occurrence_date=occurrence_date, vaccine_cvx=cvx)


def test_same_day_two_vaccines_same_encounter_id():
    """Two different CVX on the same date must synthesize the SAME encounter_id,
    so the enricher's hosted-set dedup collapses them to one Encounter."""
    patient_id = "POP-TEST-BABY"
    occ = date(2024, 6, 1)
    enc_a = _synthesize_vaccination_encounter(_imm(occ, "08"), patient_id, country="US")  # Hep B
    enc_b = _synthesize_vaccination_encounter(_imm(occ, "20"), patient_id, country="US")  # DTaP
    assert enc_a.encounter_id == enc_b.encounter_id, (
        f"Same-day CVX 08 + CVX 20 must share encounter_id; got {enc_a.encounter_id!r} vs {enc_b.encounter_id!r}"
    )


def test_different_date_different_encounter_id():
    """Vaccines on different dates must still get distinct encounters."""
    patient_id = "POP-TEST-BABY"
    enc_june = _synthesize_vaccination_encounter(_imm(date(2024, 6, 1), "08"), patient_id, country="US")
    enc_aug = _synthesize_vaccination_encounter(_imm(date(2024, 8, 1), "08"), patient_id, country="US")
    assert enc_june.encounter_id != enc_aug.encounter_id


def test_different_patient_different_encounter_id():
    """Same date + same CVX across patients must still get distinct encounters."""
    occ = date(2024, 6, 1)
    enc_a = _synthesize_vaccination_encounter(_imm(occ, "08"), "POP-A-BABY", country="US")
    enc_b = _synthesize_vaccination_encounter(_imm(occ, "08"), "POP-B-BABY", country="US")
    assert enc_a.encounter_id != enc_b.encounter_id
