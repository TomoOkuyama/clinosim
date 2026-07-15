import json

import pytest

from clinosim.modules.document.narrative.passes import TemplateNarrativePass


def _cohort(tmp_path):
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    (structural / "ENC-1.json").write_text(
        json.dumps(
            {
                "patient": {"patient_id": "POP-1", "age": 65, "sex": "M"},
                "encounters": [{"encounter_id": "ENC-1", "encounter_type": {"value": "inpatient"}}],
                "documents": [
                    {
                        "document_id": "doc-1",
                        "task_type": "admission_hp",
                        "loinc_code": "34117-2",
                        "format_type": "composition",
                        "narrative": None,
                    }
                ],
                "vitals": [],
                "lab_results": [],
                "medications": [],
                "diagnoses": [],
                "procedures": [],
                "allergies": [],
            }
        )
    )


@pytest.mark.unit
def test_same_seed_produces_byte_identical(tmp_path, tmp_path_factory):
    _cohort(tmp_path)
    tmp2 = tmp_path_factory.mktemp("second")
    _cohort(tmp2)
    TemplateNarrativePass(cif_dir=str(tmp_path), country="US", rng_seed=42).run()
    TemplateNarrativePass(cif_dir=str(tmp2), country="US", rng_seed=42).run()
    a = (tmp_path / "narratives/template/documents/ENC-1/doc-1.json").read_bytes()
    b = (tmp2 / "narratives/template/documents/ENC-1/doc-1.json").read_bytes()
    assert a == b
