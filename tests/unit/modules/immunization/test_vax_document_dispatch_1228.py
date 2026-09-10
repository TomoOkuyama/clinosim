"""Issue #1228: `enrich_immunizations` dispatches document stubs for
companion vaccination encounters.

Enricher stage order:
- `document_enricher` = POST_ENCOUNTER (early)
- `enrich_immunizations` = POST_RECORDS (late)

PR #1214 appends `ENC-VAX-*` companion encounters to `record.encounters`
in the POST_RECORDS pass. Because `document_enricher` had already walked
`record.encounters` in POST_ENCOUNTER, those new encounters received no
document stub → no narrative → FHIR export produced Encounter without a
matching DocumentReference / Composition (clinical fidelity gap for
predicting-visit notes).

Fix (Option A per Issue #1228):
1. Make `document_enricher` idempotent — skip encounters that already
   carry any document (guard by ``encounter_id``).
2. `enrich_immunizations` calls `document_enricher(ctx)` once at the end
   of its loop when any companion vaccination encounter was appended, so
   the new encounters receive their document stubs while every existing
   encounter's document set stays byte-identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from types import SimpleNamespace

from clinosim.modules.immunization.enricher import enrich_immunizations
from clinosim.types.encounter import Encounter, EncounterStatus, EncounterType, ImmunizationRecord


@dataclass
class _StubConfig:
    country: str = "JP"
    time_range: tuple[str, str] = ("2025-09-08", "2026-09-07")
    snapshot_date: str = "2026-09-07"


@dataclass
class _StubCtx:
    master_seed: int = 42
    config: object = None
    records: list = None  # type: ignore
    roster: object = None


def _mk_record(pid: str, encounters: list, documents: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        patient=SimpleNamespace(patient_id=pid, date_of_birth=date(1980, 1, 1), sex="F"),
        encounters=encounters,
        immunizations=[],
        documents=documents if documents is not None else [],
        extensions={},
        physiological_states=[],
    )


def test_vax_encounter_gets_document_stub_when_appended(monkeypatch) -> None:
    """Fix core: `enrich_immunizations` triggers document dispatch for the new VAX encounter."""

    def _fake_gen(patient, schedule, as_of, rng, nurse_ids=None):
        return [ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 3, 15))]

    monkeypatch.setattr("clinosim.modules.immunization.enricher.generate_immunizations", _fake_gen)
    monkeypatch.setattr("clinosim.modules.immunization.enricher.load_schedule", lambda country: {})

    ctx = _StubCtx()
    ctx.config = _StubConfig()
    # An unrelated outpatient encounter so document_enricher has some pre-existing docs
    # to test the idempotency guard.
    existing_enc = Encounter(
        encounter_id="ENC-EXISTING-1",
        patient_id="pt-x",
        encounter_type=EncounterType.OUTPATIENT,
        status=EncounterStatus.COMPLETED,
        admission_datetime=datetime(2025, 10, 15, 10, 0),
        discharge_datetime=datetime(2025, 10, 15, 10, 30),
        chief_complaint="Chronic follow-up",
    )
    ctx.records = [_mk_record("pt-x", [existing_enc])]

    # Simulate document_enricher having already run at POST_ENCOUNTER — stub a
    # ClinicalDocument for the existing encounter so the idempotency guard has
    # something to skip.
    from clinosim.types.clinical import ClinicalDocument

    ctx.records[0].documents = [
        ClinicalDocument(
            document_id="doc-existing-01",
            task_type="outpatient_soap",
            loinc_code="34131-3",
            patient_id="pt-x",
            encounter_id="ENC-EXISTING-1",
            authored_datetime="2025-10-15T10:00:00",
        )
    ]

    enrich_immunizations(ctx)

    rec = ctx.records[0]
    vax_encs = [e for e in rec.encounters if e.encounter_id.startswith("ENC-VAX-")]
    assert len(vax_encs) == 1
    vax_id = vax_encs[0].encounter_id

    # A document stub for the VAX encounter must now exist.
    vax_docs = [d for d in rec.documents if d.encounter_id == vax_id]
    assert len(vax_docs) >= 1, (
        f"expected document stub for {vax_id}, got docs={[d.encounter_id for d in rec.documents]}"
    )

    # The existing document is still there, byte-identical (idempotency).
    existing_docs = [d for d in rec.documents if d.encounter_id == "ENC-EXISTING-1"]
    assert len(existing_docs) == 1, "existing document must not be duplicated by re-invoke"
    assert existing_docs[0].document_id == "doc-existing-01"


def test_no_dispatch_when_no_vax_encounter_appended(monkeypatch) -> None:
    """When immunization align finds real encounters (no VAX companion), no re-dispatch."""

    def _fake_gen(patient, schedule, as_of, rng, nurse_ids=None):
        return [ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 3, 15))]

    monkeypatch.setattr("clinosim.modules.immunization.enricher.generate_immunizations", _fake_gen)
    monkeypatch.setattr("clinosim.modules.immunization.enricher.load_schedule", lambda country: {})

    ctx = _StubCtx()
    ctx.config = _StubConfig()
    # Outpatient encounter same day as the immunization — aligner binds to it.
    op_enc = Encounter(
        encounter_id="ENC-OP-1",
        patient_id="pt-y",
        encounter_type=EncounterType.OUTPATIENT,
        status=EncounterStatus.COMPLETED,
        admission_datetime=datetime(2026, 3, 15, 10, 0),
        discharge_datetime=datetime(2026, 3, 15, 10, 30),
    )
    ctx.records = [_mk_record("pt-y", [op_enc])]
    initial_doc_count = len(ctx.records[0].documents)

    enrich_immunizations(ctx)

    rec = ctx.records[0]
    # No VAX companion encounter was created — align bound to ENC-OP-1.
    assert not any(e.encounter_id.startswith("ENC-VAX-") for e in rec.encounters)
    # document_enricher must NOT be invoked (short-circuit) — doc list stays at
    # its pre-enricher count (0 in this stub setup).
    assert len(rec.documents) == initial_doc_count


def test_pre_sim_historical_dose_does_not_trigger_dispatch(monkeypatch) -> None:
    """Pre-sim historical dose leaves encounter empty, so no VAX encounter → no dispatch."""

    def _fake_gen(patient, schedule, as_of, rng, nurse_ids=None):
        return [ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2015, 5, 1))]

    monkeypatch.setattr("clinosim.modules.immunization.enricher.generate_immunizations", _fake_gen)
    monkeypatch.setattr("clinosim.modules.immunization.enricher.load_schedule", lambda country: {})

    ctx = _StubCtx()
    ctx.config = _StubConfig()
    ctx.records = [_mk_record("pt-h", [])]

    enrich_immunizations(ctx)

    rec = ctx.records[0]
    assert not any(e.encounter_id.startswith("ENC-VAX-") for e in rec.encounters)
    assert rec.immunizations[0].primary_source is False
    assert len(rec.documents) == 0
