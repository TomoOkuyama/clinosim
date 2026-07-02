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
    """When narratives/<version>/documents/ exists but has no per-encounter
    subdirectory (e.g. narrate pass ran but skipped this encounter), stubs
    stay ``narrative=None`` — no crash, no silent write.
    """
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(json.dumps({
        "patient": {"patient_id": "POP-1"},
        "encounters": [{"encounter_id": "ENC-1"}],
        "documents": [{"document_id": "doc-1", "narrative": None}],
    }))
    # narratives/template/documents/ exists so CIFReader init doesn't raise;
    # the per-encounter subdir ENC-1/ does NOT exist, so merge is a no-op.
    (tmp_path / "narratives" / "template" / "documents").mkdir(parents=True)
    r = CIFReader(str(tmp_path), narrative_version="template")
    patients = list(r.iter_patients())
    assert patients[0]["documents"][0]["narrative"] is None


@pytest.mark.unit
def test_reader_explicit_missing_version_raises(tmp_path):
    """F-1 fix: passing an explicit narrative_version whose directory does
    not exist must raise FileNotFoundError. Prior silent-no-op behavior
    produced empty DocumentReference / Composition FHIR output when a user
    typo'd the --narrative-version CLI arg (xhigh review root-cause).
    """
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text("{}")
    with pytest.raises(FileNotFoundError, match="typo_v1"):
        CIFReader(str(tmp_path), narrative_version="typo_v1")


@pytest.mark.unit
def test_reader_current_pointer_missing_version_raises(tmp_path):
    """F-1 fix: 'current' pointer file exists but points at a missing
    directory (broken generate/narrate flow) must raise — this is NOT
    the same as the pointer-absent fallback case."""
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text("{}")
    narratives = tmp_path / "narratives"
    narratives.mkdir()
    (narratives / "current_version.txt").write_text("missing_v")
    with pytest.raises(FileNotFoundError, match="missing_v"):
        CIFReader(str(tmp_path))


@pytest.mark.unit
def test_reader_current_no_pointer_no_template_warns_but_reads(tmp_path, caplog):
    """F-1 fix: 'current' with no pointer AND no 'template/' dir is a
    legitimate structural-only mode (pre-narrate export, or a hand-built
    test fixture). Log a warning but don't raise — silent no-op is
    acceptable when the user did not request a specific version."""
    import logging

    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(json.dumps({
        "encounters": [{"encounter_id": "ENC-1"}],
        "documents": [{"document_id": "doc-1", "narrative": None}],
    }))
    with caplog.at_level(logging.WARNING):
        r = CIFReader(str(tmp_path))
    assert any("structural-only" in rec.message for rec in caplog.records)
    # Reader is still usable; structural fields load, docs retain narrative=None.
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
