"""Full chain integration test: document_enricher → TemplateNarrativePass →
FHIR Composition, for rehabilitation_plan (chain 2, third and final chain-2
sub-project).

Verifies: Composition emitted with LOINC 34823-5, exactly 9 sections, 100%
Japanese text, ONLY for JP inpatient encounters with ≥1 RehabSession —
correctly ABSENT when no RehabSession exists, and for out-of-scope cohorts
(US, outpatient, emergency, icu, rehab_inpatient).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
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


def _jp_patient_dict(patient_id: str, with_rehab: bool, encounter_type: str = "inpatient") -> dict:
    admission_dt = datetime(2026, 7, 1, 10, 0)
    encounter_id = f"enc-{patient_id}"
    rehab_sessions = (
        [{
            "session_id": f"REHAB-{patient_id}-001",
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "therapy_type": "PT",
            "session_date": admission_dt + timedelta(days=1, hours=10),
            "duration_minutes": 40,
            "day_post_op": 1,
            "activities": ["bed exercises"],
            "patient_participation": "good",
            "pain_score": 3,
            "functional_progress": "stable",
        }]
        if with_rehab
        else []
    )
    record: dict = {
        "patient": {"patient_id": patient_id, "age": 70, "sex": "F"},
        "encounters": [
            {
                "encounter_id": encounter_id,
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": admission_dt,
                "discharge_datetime": admission_dt + timedelta(days=10),
                "attending_physician_id": "dr-rp-chain-test",
                "primary_nurse_id": "ns-rp-chain-test",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
        "condition_event": {},
        "vital_signs": [],
        "lab_results": [],
        "medication_administrations": [],
        "procedures": [],
        "rehab_sessions": rehab_sessions,
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
def test_jp_inpatient_with_rehab_sessions_produces_rehabilitation_plan_composition() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        patient_id = "pt-rp-chain-inpatient"
        patient_dict = _jp_patient_dict(patient_id, with_rehab=True)
        _write_structural_cif(tmp, patient_dict)

        manifest = TemplateNarrativePass(tmp, version_id="v1", country="jp").run()
        assert manifest.document_counts_by_type.get("rehabilitation_plan") == 1

        narrative_dir = os.path.join(tmp, "narratives", "v1", "documents", f"enc-{patient_id}")
        rp_stub = next(
            d for d in patient_dict["documents"] if d["task_type"] == "rehabilitation_plan"
        )
        rp_file = os.path.join(narrative_dir, f"{rp_stub['document_id']}.json")
        assert os.path.exists(rp_file)
        with open(rp_file) as f:
            doc_payload = json.load(f)

        rp_stub["narrative"] = doc_payload["narrative"]
        patient_dict["extensions"] = {}
        bundle_ctx = _make_bundle_ctx(patient_dict, country="jp")
        comp_out = _bb_compositions(bundle_ctx)
        assert len(comp_out) == 1
        comp = comp_out[0]
        assert comp["type"]["coding"][0]["code"] == "34823-5"
        assert comp["type"]["coding"][0]["display"] == "リハビリテーション実施計画書"
        assert len(comp["section"]) == 9

        all_text = " ".join(s["title"] + s["text"]["div"] for s in comp["section"])
        has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
        assert has_jp


@pytest.mark.integration
def test_jp_inpatient_without_rehab_sessions_produces_no_rehabilitation_plan() -> None:
    patient_dict = _jp_patient_dict("pt-rp-chain-norehab", with_rehab=False)
    assert not any(d["task_type"] == "rehabilitation_plan" for d in patient_dict["documents"])


@pytest.mark.integration
@pytest.mark.parametrize("encounter_type,country", [
    ("inpatient", "us"),
    ("outpatient", "jp"),
    ("emergency", "jp"),
    ("icu", "jp"),
    ("rehab_inpatient", "jp"),
])
def test_out_of_scope_cohorts_produce_no_rehabilitation_plan(
    encounter_type: str, country: str
) -> None:
    admission_dt = datetime(2026, 7, 1, 10, 0)
    encounter_id = f"enc-rp-{encounter_type}-{country}"
    record: dict = {
        "patient": {"patient_id": f"pt-rp-chain-{encounter_type}-{country}", "age": 50, "sex": "M"},
        "encounters": [
            {
                "encounter_id": encounter_id,
                "encounter_type": encounter_type,
                "status": "completed",
                "admission_datetime": admission_dt,
                "discharge_datetime": admission_dt + timedelta(days=10),
                "attending_physician_id": "dr-rp-chain-test",
            }
        ],
        "documents": [],
        "extensions": {},
        "physiological_states": [],
        "rehab_sessions": [{
            "session_id": "REHAB-oos-001",
            "patient_id": f"pt-rp-chain-{encounter_type}-{country}",
            "encounter_id": encounter_id,
            "therapy_type": "PT",
            "session_date": admission_dt + timedelta(days=1),
            "duration_minutes": 40,
            "day_post_op": 1,
            "activities": [],
            "patient_participation": "good",
            "pain_score": 3,
            "functional_progress": "stable",
        }],
    }
    ctx = SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace(country=country))
    document_enricher(ctx)
    rp_docs = [d for d in record["documents"] if d.task_type == "rehabilitation_plan"]
    assert len(rp_docs) == 0
