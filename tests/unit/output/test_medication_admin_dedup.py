"""MedicationAdministration hour-bucket dedup — Issue #1187 F5.

Root cause: a 25-day inpatient stay recorded 33 doses of atorvastatin
and 28 of amlodipine for daily prescriptions (`admin_hours=[8]`).
Duplicate CIF Orders, STAT/day-0 ad-hoc dosing paths, and home-med
continuation orders each independently emit MARs — the FHIR bundle
ships all of them. The emit-time hour-bucket dedup collapses same-
drug MARs falling in the same hour on the same patient.
"""

from __future__ import annotations

from clinosim.modules.output.fhir_r4.lib.inline_bb import _dedup_medication_admins


def _mk(drug: str, eff: str, patient: str = "pt-x", ma_id: str = "") -> dict:
    return {
        "resourceType": "MedicationAdministration",
        "id": ma_id or f"ma-{drug}-{eff}",
        "subject": {"reference": f"Patient/{patient}"},
        "medicationCodeableConcept": {"text": drug},
        "effectiveDateTime": eff,
    }


def test_no_duplicates_returns_all() -> None:
    mas = [
        _mk("atorvastatin", "2026-05-01T08:00:00"),
        _mk("atorvastatin", "2026-05-02T08:00:00"),
    ]
    assert len(_dedup_medication_admins(mas)) == 2


def test_same_hour_same_drug_same_patient_dedup() -> None:
    mas = [
        _mk("atorvastatin", "2026-05-01T08:00:00", ma_id="ma-a"),
        _mk("atorvastatin", "2026-05-01T08:05:00", ma_id="ma-b"),  # 5 min jitter
    ]
    out = _dedup_medication_admins(mas)
    assert len(out) == 1
    assert out[0]["id"] == "ma-a"


def test_different_hours_kept() -> None:
    mas = [
        _mk("cephem", "2026-05-01T08:00:00"),
        _mk("cephem", "2026-05-01T14:00:00"),  # BID / q6h
        _mk("cephem", "2026-05-01T20:00:00"),
    ]
    assert len(_dedup_medication_admins(mas)) == 3


def test_different_drugs_same_hour_kept() -> None:
    mas = [
        _mk("atorvastatin", "2026-05-01T08:00:00"),
        _mk("amlodipine", "2026-05-01T08:00:00"),
    ]
    assert len(_dedup_medication_admins(mas)) == 2


def test_different_patients_same_hour_kept() -> None:
    mas = [
        _mk("atorvastatin", "2026-05-01T08:00:00", patient="pt-1"),
        _mk("atorvastatin", "2026-05-01T08:00:00", patient="pt-2"),
    ]
    assert len(_dedup_medication_admins(mas)) == 2


def test_effective_period_falls_back_to_start() -> None:
    mas = [
        {
            "resourceType": "MedicationAdministration",
            "subject": {"reference": "Patient/pt-x"},
            "medicationCodeableConcept": {"text": "furosemide"},
            "effectivePeriod": {"start": "2026-05-01T09:00:00"},
        },
        {
            "resourceType": "MedicationAdministration",
            "subject": {"reference": "Patient/pt-x"},
            "medicationCodeableConcept": {"text": "furosemide"},
            "effectivePeriod": {"start": "2026-05-01T09:15:00"},
        },
    ]
    assert len(_dedup_medication_admins(mas)) == 1


def test_25_day_daily_drug_collapses_from_50_to_25() -> None:
    # Simulate the #1187 F5 pattern: two orders for the same daily drug
    # each fire a MAR at 08:00 for 25 days.
    mas = []
    for d in range(25):
        eff = f"2026-05-{d + 1:02d}T08:00:00"
        mas.append(_mk("atorvastatin", eff, ma_id=f"ma-order-a-day-{d}"))
        mas.append(_mk("atorvastatin", eff, ma_id=f"ma-order-b-day-{d}"))
    out = _dedup_medication_admins(mas)
    assert len(out) == 25  # exactly one per day survives


def test_empty_drug_or_time_passes_through() -> None:
    mas = [
        {"medicationCodeableConcept": {"text": ""}, "effectiveDateTime": "2026-05-01T08:00:00"},
        {"medicationCodeableConcept": {"text": "atorvastatin"}, "effectiveDateTime": ""},
    ]
    # Neither can key on (drug, hour_bucket, subject) so both pass through.
    assert len(_dedup_medication_admins(mas)) == 2
