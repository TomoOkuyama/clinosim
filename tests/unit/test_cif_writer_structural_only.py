import json
from datetime import date, datetime

import pytest

from clinosim.modules.output.cif_writer import write_cif
from clinosim.types.clinical import ClinicalDocument, ClinicalDocumentNarrative
from clinosim.types.output import (
    CIFDataset,
    CIFMetadata,
    CIFPatientRecord,
    Encounter,
    PatientProfile,
)


def _tiny_dataset() -> CIFDataset:
    doc_with_narr = ClinicalDocument(
        document_id="doc-1",
        loinc_code="34117-2",
        narrative=ClinicalDocumentNarrative(text="SHOULD BE STRIPPED"),
    )
    doc_stub = ClinicalDocument(document_id="doc-2", loinc_code="34746-8", narrative=None)
    p = CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-000001", age=65, sex="M", date_of_birth=date(1961, 1, 1)),
        encounters=[
            Encounter(
                encounter_id="ENC-1",
                encounter_type=None,
                admission_datetime=datetime(2026, 1, 1, 9, 0),
            )
        ],
        documents=[doc_with_narr, doc_stub],
    )
    md = CIFMetadata(
        clinosim_version="0.1.0",
        random_seed=42,
        country="US",
        hospital_scale="medium",
        snapshot_date="2026-07-01",
        total_patients_generated=1,
        llm_mode="none",
    )
    return CIFDataset(metadata=md, patients=[p], hospital_roster=[], hospital_config={})


@pytest.mark.unit
def test_write_cif_strips_narrative_from_documents(tmp_path):
    write_cif(_tiny_dataset(), str(tmp_path))
    path = tmp_path / "structural" / "patients" / "ENC-1.json"
    assert path.exists()
    data = json.loads(path.read_text())
    docs = data["documents"]
    assert len(docs) == 2
    for d in docs:
        assert d["narrative"] is None, f"narrative must be stripped, got {d['narrative']}"


@pytest.mark.unit
def test_write_cif_preserves_structural_fields(tmp_path):
    write_cif(_tiny_dataset(), str(tmp_path))
    data = json.loads((tmp_path / "structural" / "patients" / "ENC-1.json").read_text())
    doc = data["documents"][0]
    assert doc["document_id"] == "doc-1"
    assert doc["loinc_code"] == "34117-2"
