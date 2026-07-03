"""β-JP-1 chain 1b T3: `narrate --patient-filter` regex on the NarrativePass walk.

Contract: the filter matches against the patient JSON filename stem AND the
patient_id inside the file; None (default) = all patients (behavior
unchanged); the manifest records the filter; filtered output is
byte-identical to the unfiltered run for the selected patients (AD-16).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from clinosim.modules.document.narrative.passes import TemplateNarrativePass

pytestmark = pytest.mark.unit


def _write_patient(structural: Path, enc_id: str, patient_id: str) -> None:
    payload = {
        "patient": {
            "patient_id": patient_id,
            "age": 65,
            "sex": "M",
            "chronic_conditions": [],
        },
        "encounters": [
            {
                "encounter_id": enc_id,
                "encounter_type": {"value": "inpatient"},
                "attending_physician_id": "DR-1",
                "admission_diagnosis_code": "I21.4",
            }
        ],
        "documents": [
            {
                "document_id": f"doc-{enc_id}",
                "task_type": "admission_hp",
                "loinc_code": "34117-2",
                "narrative": None,
                "format_type": "composition",
            }
        ],
    }
    (structural / f"{enc_id}.json").write_text(json.dumps(payload, ensure_ascii=False))


def _write_cohort(tmp_path: Path) -> Path:
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    _write_patient(structural, "ENC-A", "POP-000001")
    _write_patient(structural, "ENC-B", "POP-000002")
    _write_patient(structural, "ENC-C", "POP-000777")
    return tmp_path


def _narrated_encounters(cif_dir: Path, version: str = "template") -> set[str]:
    docs = cif_dir / "narratives" / version / "documents"
    if not docs.is_dir():
        return set()
    return {d.name for d in docs.iterdir() if d.is_dir()}


def test_no_filter_processes_all_patients(tmp_path: Path) -> None:
    _write_cohort(tmp_path)
    manifest = TemplateNarrativePass(cif_dir=str(tmp_path), country="US").run()
    assert _narrated_encounters(tmp_path) == {"ENC-A", "ENC-B", "ENC-C"}
    assert manifest.patient_filter == ""


def test_filter_by_filename_stem_selects_subset(tmp_path: Path) -> None:
    _write_cohort(tmp_path)
    manifest = TemplateNarrativePass(
        cif_dir=str(tmp_path), country="US", patient_filter="ENC-A",
    ).run()
    assert _narrated_encounters(tmp_path) == {"ENC-A"}
    assert manifest.document_count == 1
    assert manifest.patient_filter == "ENC-A"


def test_filter_by_patient_id_selects_subset(tmp_path: Path) -> None:
    """Regex matching only the patient_id (not the filename) still selects."""
    _write_cohort(tmp_path)
    TemplateNarrativePass(
        cif_dir=str(tmp_path), country="US", patient_filter="POP-000777",
    ).run()
    assert _narrated_encounters(tmp_path) == {"ENC-C"}


def test_filter_regex_alternation(tmp_path: Path) -> None:
    _write_cohort(tmp_path)
    TemplateNarrativePass(
        cif_dir=str(tmp_path), country="US", patient_filter="ENC-A|POP-000777",
    ).run()
    assert _narrated_encounters(tmp_path) == {"ENC-A", "ENC-C"}


def test_filtered_output_byte_identical_to_unfiltered(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """AD-16: for a selected patient, the filter must not change one byte."""
    _write_cohort(tmp_path)
    full = tmp_path_factory.mktemp("unfiltered")
    _write_cohort(full)
    TemplateNarrativePass(
        cif_dir=str(tmp_path), country="US", rng_seed=42, patient_filter="ENC-B",
    ).run()
    TemplateNarrativePass(cif_dir=str(full), country="US", rng_seed=42).run()
    a = (tmp_path / "narratives/template/documents/ENC-B/doc-ENC-B.json").read_bytes()
    b = (full / "narratives/template/documents/ENC-B/doc-ENC-B.json").read_bytes()
    assert a == b


def test_filtered_run_deterministic(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    _write_cohort(tmp_path)
    other = tmp_path_factory.mktemp("second")
    _write_cohort(other)
    TemplateNarrativePass(
        cif_dir=str(tmp_path), country="US", rng_seed=42, patient_filter="ENC-A",
    ).run()
    TemplateNarrativePass(
        cif_dir=str(other), country="US", rng_seed=42, patient_filter="ENC-A",
    ).run()
    a = (tmp_path / "narratives/template/documents/ENC-A/doc-ENC-A.json").read_bytes()
    b = (other / "narratives/template/documents/ENC-A/doc-ENC-A.json").read_bytes()
    assert a == b


def test_invalid_filter_regex_fails_loud(tmp_path: Path) -> None:
    _write_cohort(tmp_path)
    with pytest.raises(re.error):
        TemplateNarrativePass(
            cif_dir=str(tmp_path), country="US", patient_filter="([unclosed",
        )


def test_filter_matching_nothing_writes_empty_version(tmp_path: Path) -> None:
    _write_cohort(tmp_path)
    manifest = TemplateNarrativePass(
        cif_dir=str(tmp_path), country="US", patient_filter="NO-SUCH-PATIENT",
    ).run()
    assert manifest.document_count == 0
    assert _narrated_encounters(tmp_path) == set()
