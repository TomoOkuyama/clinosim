"""Companion vaccination encounter synthesis — Issue #1197 verify Pass 5.

When `_align_to_encounters` cannot find an existing outpatient encounter
within ±60 days of an in-sim-window immunization, `enrich_immunizations`
emits a minimal `Encounter(encounter_type=OUTPATIENT, chief_complaint=
"Vaccination visit", ...)` and stamps the immunization's encounter_id.

Pre-sim historical doses stay unlinked with `primary_source=False` so
downstream consumers can filter them out (patient interview / registry
recorded; no in-sim visit).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from types import SimpleNamespace

from clinosim.modules.immunization.enricher import (
    _synthesize_vaccination_encounter,
    enrich_immunizations,
)
from clinosim.types.encounter import Encounter, EncounterStatus, EncounterType, ImmunizationRecord


def test_synth_encounter_shape() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 10, 1))
    enc = _synthesize_vaccination_encounter(imm, "POP-000001", "JP")
    assert enc.encounter_type == EncounterType.OUTPATIENT
    assert enc.status == EncounterStatus.COMPLETED
    assert enc.department_id == "primary_care"
    assert enc.admission_datetime.date() == date(2026, 10, 1)
    assert enc.chief_complaint == "Vaccination visit"
    assert enc.chief_complaint_ja == "予防接種"
    assert enc.patient_id == "POP-000001"
    assert enc.encounter_id.startswith("ENC-VAX-POP-000001-")


def test_synth_encounter_id_is_deterministic() -> None:
    imm1 = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 10, 1))
    imm2 = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 10, 1))
    enc1 = _synthesize_vaccination_encounter(imm1, "POP-000001", "JP")
    enc2 = _synthesize_vaccination_encounter(imm2, "POP-000001", "JP")
    assert enc1.encounter_id == enc2.encounter_id


def test_synth_encounter_id_varies_by_patient() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 10, 1))
    enc1 = _synthesize_vaccination_encounter(imm, "POP-000001", "JP")
    enc2 = _synthesize_vaccination_encounter(imm, "POP-000002", "JP")
    assert enc1.encounter_id != enc2.encounter_id


def test_synth_encounter_us_has_no_ja_chief() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 10, 1))
    enc = _synthesize_vaccination_encounter(imm, "pt-us-1", "US")
    assert enc.chief_complaint_ja == ""


@dataclass
class _StubConfig:
    country: str = "US"
    time_range: tuple[str, str] = ("2025-09-08", "2026-09-07")
    snapshot_date: str = "2026-09-07"


@dataclass
class _StubCtx:
    master_seed: int = 42
    config: object = None
    records: list = None  # type: ignore
    roster: object = None


def _mk_record(pid: str, encounters: list) -> SimpleNamespace:
    return SimpleNamespace(
        patient=SimpleNamespace(patient_id=pid, date_of_birth=date(1980, 1, 1), sex="F"),
        encounters=encounters,
        immunizations=[],
    )


def test_in_window_orphan_gets_companion_encounter(monkeypatch) -> None:
    # Stub `generate_immunizations` to return an in-window orphan.
    def _fake_gen(patient, schedule, as_of, rng, nurse_ids=None):
        return [
            ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 3, 15)),
        ]

    monkeypatch.setattr("clinosim.modules.immunization.enricher.generate_immunizations", _fake_gen)
    monkeypatch.setattr("clinosim.modules.immunization.enricher.load_schedule", lambda country: {})

    ctx = _StubCtx()
    ctx.config = _StubConfig(country="US", time_range=("2025-09-08", "2026-09-07"))
    # A patient with only inpatient encounters — no outpatient to align to.
    inp_enc = Encounter(
        encounter_id="ENC-INP-1",
        patient_id="pt-x",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 12, 1, 10, 0),
    )
    ctx.records = [_mk_record("pt-x", [inp_enc])]

    enrich_immunizations(ctx)

    rec = ctx.records[0]
    assert len(rec.immunizations) == 1
    imm = rec.immunizations[0]
    assert imm.encounter_id.startswith("ENC-VAX-pt-x-")
    # Companion encounter appended to rec.encounters.
    synth = [e for e in rec.encounters if e.encounter_id.startswith("ENC-VAX-")]
    assert len(synth) == 1
    assert synth[0].encounter_id == imm.encounter_id
    assert imm.primary_source is True  # in-window: recorded from real (simulated) visit


def test_pre_sim_historical_gets_primary_source_false(monkeypatch) -> None:
    def _fake_gen(patient, schedule, as_of, rng, nurse_ids=None):
        return [
            # Pre-sim historical dose (before window start).
            ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2015, 5, 1)),
        ]

    monkeypatch.setattr("clinosim.modules.immunization.enricher.generate_immunizations", _fake_gen)
    monkeypatch.setattr("clinosim.modules.immunization.enricher.load_schedule", lambda country: {})

    ctx = _StubCtx()
    ctx.config = _StubConfig(country="US", time_range=("2025-09-08", "2026-09-07"))
    ctx.records = [_mk_record("pt-h", [])]

    enrich_immunizations(ctx)

    rec = ctx.records[0]
    assert len(rec.immunizations) == 1
    imm = rec.immunizations[0]
    assert imm.encounter_id == ""  # unlinked
    assert imm.primary_source is False  # explicit history flag
    # No companion encounter added.
    assert not any(e.encounter_id.startswith("ENC-VAX-") for e in rec.encounters)
