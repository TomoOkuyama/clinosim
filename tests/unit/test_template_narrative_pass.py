import json
from pathlib import Path

import pytest

from clinosim.modules.document.narrative.passes import TemplateNarrativePass


def _write_tiny_structural(tmp_path: Path, encounter_type: str = "inpatient") -> Path:
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    payload = {
        "patient": {
            "patient_id": "POP-000001",
            "age": 65,
            "sex": "M",
            "chronic_conditions": [],
        },
        "encounters": [
            {
                "encounter_id": "ENC-1",
                "encounter_type": {"value": encounter_type},
                "attending_physician_id": "DR-1",
                "admission_diagnosis_code": "I21.4",
            }
        ],
        "documents": [
            {
                "document_id": "doc-1",
                "task_type": "admission_hp",
                "loinc_code": "34117-2",
                "narrative": None,
                "format_type": "composition",
            }
        ],
        "vitals": [],
        "lab_results": [],
        "medications": [],
        "diagnoses": [],
        "procedures": [],
        "allergies": [],
    }
    (structural / "ENC-1.json").write_text(json.dumps(payload, ensure_ascii=False))
    return tmp_path


@pytest.mark.unit
def test_template_pass_writes_narrative_dir(tmp_path):
    _write_tiny_structural(tmp_path)
    p = TemplateNarrativePass(cif_dir=str(tmp_path), country="US")
    manifest = p.run()
    assert manifest.version_id == "template"
    assert manifest.generator == "template"
    assert manifest.document_count >= 1
    narr_dir = tmp_path / "narratives" / "template" / "documents" / "ENC-1"
    assert narr_dir.exists()
    files = list(narr_dir.iterdir())
    assert any(f.name == "admission_hp.json" for f in files)


@pytest.mark.unit
def test_template_pass_narrative_file_shape(tmp_path):
    _write_tiny_structural(tmp_path)
    TemplateNarrativePass(cif_dir=str(tmp_path), country="US").run()
    payload = json.loads(
        (tmp_path / "narratives/template/documents/ENC-1/admission_hp.json").read_text()
    )
    assert payload["document_id"] == "doc-1"
    assert payload["encounter_id"] == "ENC-1"
    assert "narrative" in payload
    n = payload["narrative"]
    assert n["generator"] == "template"
    assert "generated_at" in n
    assert isinstance(n["facts_used"], list)


@pytest.mark.unit
def test_template_pass_deterministic(tmp_path, tmp_path_factory):
    """Same seed + same structural CIF → byte-identical narrative dir."""
    _write_tiny_structural(tmp_path)
    tmp2 = tmp_path_factory.mktemp("second")
    _write_tiny_structural(tmp2)
    TemplateNarrativePass(cif_dir=str(tmp_path), country="US", rng_seed=42).run()
    TemplateNarrativePass(cif_dir=str(tmp2), country="US", rng_seed=42).run()
    a = (tmp_path / "narratives/template/documents/ENC-1/admission_hp.json").read_bytes()
    b = (tmp2 / "narratives/template/documents/ENC-1/admission_hp.json").read_bytes()
    assert a == b


@pytest.mark.unit
def test_template_pass_tasks_filter(tmp_path):
    _write_tiny_structural(tmp_path)
    p = TemplateNarrativePass(cif_dir=str(tmp_path), country="US", tasks=["progress_note"])
    manifest = p.run()
    assert manifest.document_counts_by_type.get("admission_hp", 0) == 0


@pytest.mark.unit
def test_template_pass_writes_current_pointer_manifest(tmp_path):
    _write_tiny_structural(tmp_path)
    TemplateNarrativePass(cif_dir=str(tmp_path), country="US").run()
    manifest_path = tmp_path / "narratives" / "template" / "manifest.json"
    assert manifest_path.exists()
    m = json.loads(manifest_path.read_text())
    assert m["version_id"] == "template"
    assert m["generator"] == "template"
