"""Full chain integration test: document_enricher → TemplateNarrativePass →
FHIR Composition, for admission_care_plan (chain 2).

Verifies: Composition emitted with LOINC 18776-5, exactly 10 sections, 100%
Japanese text (jp_language axis), and correctly ABSENT for out-of-scope
cohorts (US, outpatient, emergency, rehab_inpatient) — the silent-no-op
negative check the design spec §5 requires.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.engine import document_enricher
from clinosim.modules.document.narrative.passes import TemplateNarrativePass
from clinosim.modules.output._fhir_composition import _bb_compositions


def _write_structural_cif(cif_dir: str, patient_dict: dict) -> None:
    structural_dir = os.path.join(cif_dir, "structural", "patients")
    os.makedirs(structural_dir, exist_ok=True)
    path = os.path.join(structural_dir, f"{patient_dict['patient']['patient_id']}.json")
    with open(path, "w") as f:
        json.dump(patient_dict, f, default=str)


def _make_bundle_ctx(record: dict, country: str = "jp") -> SimpleNamespace:
    """Minimal BundleContext-shaped namespace (mirrors
    tests/unit/output/test_fhir_composition_alpha2.py's _make_ctx — only the
    fields _bb_compositions actually reads are populated)."""
    return SimpleNamespace(
        record=record,
        country=country,
        patient_id=record.get("patient", {}).get("patient_id", ""),
        primary_enc_id=record["encounters"][0]["encounter_id"],
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10",
        patient_sex="",
    )


def _jp_inpatient_patient_dict(patient_id: str, encounter_type: str = "inpatient") -> dict:
    record: dict = {
        "patient": {"patient_id": patient_id, "age": 68, "sex": "M"},
        "encounters": [
            {
                "encounter_id": f"enc-{patient_id}",
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": datetime(2026, 7, 1, 10, 0),
                "discharge_datetime": datetime(2026, 7, 6, 10, 0),
                "attending_physician_id": "dr-chain-test",
                "primary_nurse_id": "ns-chain-test",
                "ward_id": "4W",
                "bed_number": "401-2",
                "severity": "moderate",
                "clinical_course_archetype": "uncomplicated_improvement",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
        "condition_event": {},
        "clinical_diagnosis": {
            "admission_diagnosis_code": "J18.9",
            "admission_diagnosis_system": "icd-10",
        },
        "vital_signs": [],
        "lab_results": [],
        "medication_administrations": [],
        "procedures": [],
    }
    ctx = SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace(country="jp"))
    document_enricher(ctx)
    record["documents"] = [
        {
            "document_id": d.document_id,
            "task_type": d.task_type,
            "loinc_code": d.loinc_code,
            "encounter_id": d.encounter_id,
            "author_practitioner_id": d.author_practitioner_id,
            "authored_datetime": d.authored_datetime,
            "period_start": d.period_start,
            "period_end": d.period_end,
            "language": d.language,
            "format_type": d.format_type,
        }
        for d in record["documents"]
    ]
    return record


@pytest.mark.integration
@pytest.mark.parametrize("encounter_type", ["inpatient", "icu"])
def test_jp_inpatient_produces_admission_care_plan_composition(encounter_type: str) -> None:
    """Covers both supported encounter types (adv-1 finding: the original test
    only exercised inpatient, despite the design spec explicitly requiring
    'JP inpatient + JP ICU' coverage in this integration test)."""
    with tempfile.TemporaryDirectory() as tmp:
        patient_id = f"pt-chain-jp-{encounter_type}"
        patient_dict = _jp_inpatient_patient_dict(patient_id, encounter_type=encounter_type)
        _write_structural_cif(tmp, patient_dict)

        manifest = TemplateNarrativePass(tmp, version_id="v1", country="jp").run()
        assert manifest.document_counts_by_type.get("admission_care_plan") == 1

        narrative_dir = os.path.join(
            tmp, "narratives", "v1", "documents", f"enc-{patient_id}"
        )
        acp_stub = next(
            d for d in patient_dict["documents"] if d["task_type"] == "admission_care_plan"
        )
        acp_file = os.path.join(narrative_dir, f"{acp_stub['document_id']}.json")
        assert os.path.exists(acp_file)
        with open(acp_file) as f:
            doc_payload = json.load(f)

        acp_stub["narrative"] = doc_payload["narrative"]
        patient_dict["extensions"] = {}
        bundle_ctx = _make_bundle_ctx(patient_dict, country="jp")
        comp_out = _bb_compositions(bundle_ctx)
        assert len(comp_out) == 1
        comp = comp_out[0]
        assert comp["type"]["coding"][0]["code"] == "18776-5"
        assert comp["type"]["coding"][0]["display"] == "入院診療計画書"
        assert len(comp["section"]) == 10

        all_text = " ".join(s["title"] + s["text"]["div"] for s in comp["section"])
        has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
        assert has_jp


@pytest.mark.integration
@pytest.mark.parametrize("encounter_type,country", [
    ("inpatient", "us"),
    ("outpatient", "jp"),
    ("emergency", "jp"),
    ("rehab_inpatient", "jp"),
])
def test_out_of_scope_cohorts_produce_no_admission_care_plan(
    encounter_type: str, country: str
) -> None:
    record: dict = {
        "patient": {"patient_id": f"pt-chain-{encounter_type}-{country}", "age": 50, "sex": "F"},
        "encounters": [
            {
                "encounter_id": f"enc-{encounter_type}-{country}",
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": datetime(2026, 7, 1, 10, 0),
                "discharge_datetime": datetime(2026, 7, 3, 10, 0),
                "attending_physician_id": "dr-chain-test",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
    }
    ctx = SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace(country=country))
    document_enricher(ctx)
    acp_docs = [d for d in record["documents"] if d.task_type == "admission_care_plan"]
    assert len(acp_docs) == 0
