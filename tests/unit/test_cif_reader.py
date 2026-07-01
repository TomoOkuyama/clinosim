"""Unit tests for CIFReader (AD-65 Task 4 two-layer CIF merge loader)."""

import json
from pathlib import Path

import pytest

from clinosim.modules.output.cif_reader import CIFReader


def _make_two_layer_cif(tmp_path: Path) -> Path:
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(json.dumps({
        "patient": {"patient_id": "POP-1"},
        "encounters": [{"encounter_id": "ENC-1"}],
        "documents": [
            {"document_id": "doc-1", "task_type": "admission_hp",
             "loinc_code": "34117-2", "format_type": "composition",
             "narrative": None},
            {"document_id": "doc-2", "task_type": "progress_note",
             "loinc_code": "11506-3", "format_type": "composition",
             "narrative": None},
        ],
    }, ensure_ascii=False))

    narr_dir = tmp_path / "narratives" / "template" / "documents" / "ENC-1"
    narr_dir.mkdir(parents=True)
    (narr_dir / "admission_hp.json").write_text(json.dumps({
        "document_id": "doc-1",
        "encounter_id": "ENC-1",
        "narrative": {"text": "", "sections": {"hpi": "65yo M ..."},
                      "structured": {}, "generator": "template",
                      "generator_metadata": {}, "generated_at": "",
                      "facts_used": []},
    }, ensure_ascii=False))
    (tmp_path / "narratives" / "current_version.txt").write_text("template")
    return tmp_path


@pytest.mark.unit
def test_reader_merges_narrative_into_stub(tmp_path):
    _make_two_layer_cif(tmp_path)
    r = CIFReader(str(tmp_path))
    patients = list(r.iter_patients())
    assert len(patients) == 1
    docs = patients[0]["documents"]
    doc_map = {d["document_id"]: d for d in docs}
    assert doc_map["doc-1"]["narrative"] is not None
    assert doc_map["doc-1"]["narrative"]["sections"]["hpi"] == "65yo M ..."
    # doc-2 has no matching narrative file → stays None
    assert doc_map["doc-2"]["narrative"] is None


@pytest.mark.unit
def test_reader_current_version_default_falls_back_to_template(tmp_path):
    _make_two_layer_cif(tmp_path)
    (tmp_path / "narratives" / "current_version.txt").unlink()
    r = CIFReader(str(tmp_path))  # default "current" → template fallback
    patients = list(r.iter_patients())
    # narrative dir "template" still exists, so merge still works
    docs = patients[0]["documents"]
    assert any(d["narrative"] is not None for d in docs)


@pytest.mark.unit
def test_reader_no_narrative_dir_leaves_stubs(tmp_path):
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(json.dumps({
        "patient": {"patient_id": "POP-1"},
        "encounters": [{"encounter_id": "ENC-1"}],
        "documents": [{"document_id": "doc-1", "narrative": None}],
    }))
    r = CIFReader(str(tmp_path), narrative_version="template")
    patients = list(r.iter_patients())
    assert patients[0]["documents"][0]["narrative"] is None


@pytest.mark.unit
def test_reader_orphan_narrative_file_warns_and_drops(tmp_path, caplog):
    _make_two_layer_cif(tmp_path)
    # Add orphan narrative
    narr_dir = tmp_path / "narratives" / "template" / "documents" / "ENC-1"
    (narr_dir / "orphan.json").write_text(json.dumps({
        "document_id": "doc-missing",
        "encounter_id": "ENC-1",
        "narrative": {"text": "orphan"},
    }))
    r = CIFReader(str(tmp_path))
    list(r.iter_patients())
    assert any("orphan" in rec.message.lower() or "doc-missing" in rec.message
               for rec in caplog.records)


@pytest.mark.unit
def test_reader_missing_structural_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        list(CIFReader(str(tmp_path)).iter_patients())


@pytest.mark.unit
def test_reader_explicit_version_overrides_current_pointer(tmp_path):
    _make_two_layer_cif(tmp_path)
    (tmp_path / "narratives" / "current_version.txt").write_text("some_other_version")
    r = CIFReader(str(tmp_path), narrative_version="template")
    patients = list(r.iter_patients())
    doc_map = {d["document_id"]: d for d in patients[0]["documents"]}
    assert doc_map["doc-1"]["narrative"] is not None
