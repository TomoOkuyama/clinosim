"""Tests for clinical document generation pipeline.

Covers:
- PromptRegistry (YAML loading + Template rendering)
- PromptCache (SHA256 disk cache)
- Provider factory (build_provider / build_from_config)
- LLMService routing with PromptRegistry + cache
- Hospital course extractor
- Document generator (CIF → ClinicalDocument stubs)
- FHIR DocumentReference builder
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from clinosim.modules.llm_service.cache import PromptCache
from clinosim.modules.llm_service.engine import (
    ClinicalEventData,
    DOCUMENT_LOINC,
    LLMService,
    LLMTaskType,
    PatientSummary,
    loinc_for,
)
from clinosim.modules.llm_service.factory import build_from_config
from clinosim.modules.llm_service.prompt_registry import PromptRegistry, _stringify
from clinosim.modules.llm_service.providers import (
    BedrockProvider,
    MockProvider,
    OllamaProvider,
    build_provider,
)
from clinosim.modules.llm_service.providers.base import ProviderResponse
from clinosim.modules.output.document_generator import (
    _PROCEDURE_NOTE_TYPES,
    generate_documents,
)
from clinosim.modules.output.fhir_r4_adapter import _build_document_reference
from clinosim.modules.output.hospital_course_extractor import (
    extract_hospital_course,
    summarize_admission_vitals,
    summarize_discharge_medications,
    summarize_procedures,
)
from clinosim.types.clinical import ClinicalDocument


# ---------------------------------------------------------------------------
# PromptRegistry
# ---------------------------------------------------------------------------


class TestPromptRegistry:
    def test_loads_all_tier_ab_prompts(self):
        reg = PromptRegistry()
        for task in [
            "discharge_summary",
            "death_summary",
            "operative_note",
            "admission_hp",
            "procedure_note",
        ]:
            spec = reg.get(task, "en")
            assert spec.system, f"{task} missing system prompt"
            assert spec.user_template, f"{task} missing user template"
            assert spec.max_tokens > 0
            assert spec.version >= 1

    def test_language_fallback_to_en(self):
        reg = PromptRegistry()
        # ja not implemented yet → falls back to en
        spec = reg.get("discharge_summary", "ja")
        assert spec.system  # en content loaded

    def test_render_substitutes_variables(self):
        reg = PromptRegistry()
        spec = reg.get("operative_note", "en")
        system, user = spec.render(
            {
                "surgery_date": "2026-03-15",
                "procedure_name": "ORIF femur",
                "procedure_code": "27236",
                "preop_diagnosis": "Right hip fracture",
                "postop_diagnosis": "Right hip fracture",
                "surgeon": "DR-SU-01",
                "assistants": ["DR-SU-02"],
                "anesthesiologist": "DR-AN-01",
                "anesthesia_type": "spinal",
                "asa_class": 3,
                "duration_minutes": 90,
                "estimated_blood_loss_ml": 300,
                "body_site": "Bone structure of femur",
                "approach": "lateral",
                "implants_used": ["compression hip screw"],
                "specimens_sent": [],
                "intraop_complications": [],
                "outcome": "Successful",
            }
        )
        assert "ORIF femur" in user
        assert "DR-SU-01" in user
        assert "system" not in system.lower() or "surgeon" in system.lower()

    def test_missing_variable_raises(self):
        reg = PromptRegistry()
        spec = reg.get("discharge_summary", "en")
        with pytest.raises(KeyError):
            spec.render({"age": 65})  # many other vars missing

    def test_stringify_list_as_bullets(self):
        result = _stringify(["Aspirin 81mg", "Atorvastatin 40mg"])
        assert "- Aspirin 81mg" in result
        assert "- Atorvastatin 40mg" in result

    def test_stringify_empty_list_is_none_placeholder(self):
        assert _stringify([]) == "(none)"


# ---------------------------------------------------------------------------
# PromptCache
# ---------------------------------------------------------------------------


class TestPromptCache:
    def test_roundtrip(self, tmp_path):
        cache = PromptCache(tmp_path, enabled=True)
        assert cache.get("sys", "user", "model") is None
        cache.put(
            "sys",
            "user",
            "model",
            ProviderResponse(text="hello", input_tokens=10, output_tokens=5, model="m"),
        )
        r = cache.get("sys", "user", "model")
        assert r is not None
        assert r.text == "hello"
        assert r.input_tokens == 10

    def test_cache_disabled_returns_none(self, tmp_path):
        cache = PromptCache(tmp_path, enabled=False)
        cache.put("s", "u", "m", ProviderResponse(text="x"))
        assert cache.get("s", "u", "m") is None

    def test_different_prompts_different_keys(self, tmp_path):
        cache = PromptCache(tmp_path, enabled=True)
        cache.put("s1", "u1", "m", ProviderResponse(text="a"))
        cache.put("s2", "u1", "m", ProviderResponse(text="b"))
        assert cache.get("s1", "u1", "m").text == "a"
        assert cache.get("s2", "u1", "m").text == "b"


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------


class TestProviders:
    def test_mock_provider_registered(self):
        p = build_provider("mock", {})
        assert isinstance(p, MockProvider)

    def test_ollama_provider_registered(self):
        p = build_provider("ollama", {"endpoint": "http://x", "model": "m"})
        assert isinstance(p, OllamaProvider)

    def test_bedrock_provider_lazy_import(self):
        # Should not raise even without boto3 installed — lazy import
        p = build_provider("bedrock", {"region": "us-east-1"})
        assert isinstance(p, BedrockProvider)
        assert p.region == "us-east-1"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            build_provider("not-a-provider", {})

    def test_mock_complete_is_deterministic(self):
        p = MockProvider()
        r1 = p.complete("hello world", model="m")
        assert r1.text.startswith("[Mock LLM response #1]")
        r2 = p.complete("hello world", model="m")
        assert r2.text.startswith("[Mock LLM response #2]")


# ---------------------------------------------------------------------------
# LLMService — wiring
# ---------------------------------------------------------------------------


class TestLLMServiceWiring:
    def test_factory_builds_mock_service(self, tmp_path):
        cfg = {
            "judgment": {"mode": "template", "provider": ""},
            "narrative": {
                "mode": "llm",
                "provider": "mock",
                "mock": {},
                "model_map": {"small": "mock", "medium": "mock"},
                "retry_attempts": 1,
            },
            "cache": {"enabled": True, "directory": str(tmp_path / "cache")},
        }
        svc = build_from_config(cfg)
        assert svc.mode == "llm"
        assert isinstance(svc.narrative_provider, MockProvider)
        assert svc.cache is not None and svc.cache.enabled

    def test_generate_uses_prompt_registry_when_variables_given(self, tmp_path):
        svc = build_from_config(
            {
                "judgment": {"mode": "template"},
                "narrative": {
                    "mode": "llm",
                    "provider": "mock",
                    "mock": {},
                    "model_map": {"small": "mock", "medium": "mock"},
                    "retry_attempts": 1,
                },
                "cache": {"enabled": True, "directory": str(tmp_path)},
            }
        )
        variables = _discharge_summary_variables()
        ps = PatientSummary(age=68, sex="Male", country="US")
        event = ClinicalEventData(patient_summary=ps, event_data={}, language="en")

        r1 = svc.generate(LLMTaskType.DISCHARGE_SUMMARY, event, variables=variables)
        assert r1.source == "llm"
        assert r1.text
        assert r1.prompt_version == 1

        # Second call → cache hit
        r2 = svc.generate(LLMTaskType.DISCHARGE_SUMMARY, event, variables=variables)
        assert r2.source == "cache"
        assert r2.cache_hit is True
        assert r2.text == r1.text


# ---------------------------------------------------------------------------
# LOINC mapping
# ---------------------------------------------------------------------------


class TestDocumentLoinc:
    def test_tier_a_b_tasks_have_loinc(self):
        for task in [
            LLMTaskType.DISCHARGE_SUMMARY,
            LLMTaskType.DEATH_SUMMARY,
            LLMTaskType.OPERATIVE_NOTE,
            LLMTaskType.ADMISSION_HP,
            LLMTaskType.PROCEDURE_NOTE,
        ]:
            assert loinc_for(task), f"{task} missing LOINC"

    def test_known_loinc_codes(self):
        assert DOCUMENT_LOINC[LLMTaskType.DISCHARGE_SUMMARY] == "18842-5"
        assert DOCUMENT_LOINC[LLMTaskType.DEATH_SUMMARY] == "69730-0"
        assert DOCUMENT_LOINC[LLMTaskType.OPERATIVE_NOTE] == "11504-8"
        assert DOCUMENT_LOINC[LLMTaskType.ADMISSION_HP] == "34117-2"
        assert DOCUMENT_LOINC[LLMTaskType.PROCEDURE_NOTE] == "28570-0"


# ---------------------------------------------------------------------------
# Hospital course extractor
# ---------------------------------------------------------------------------


class TestHospitalCourseExtractor:
    def test_empty_record_still_produces_admission_discharge(self):
        record = {"encounters": [{"admission_datetime": "2026-03-01T09:00:00"}]}
        facts = extract_hospital_course(record, "en")
        assert any(f.event_type == "admission" for f in facts)

    def test_sorting_by_day(self):
        record = {
            "encounters": [
                {
                    "admission_datetime": "2026-03-01T09:00:00",
                    "discharge_datetime": "2026-03-08T10:00:00",
                    "chief_complaint": "Chest pain",
                }
            ],
            "clinical_diagnosis": {
                "admission_diagnosis_code": "I21.9",
                "admission_diagnosis_system": "icd-10-cm",
                "discharge_diagnosis_code": "I21.9",
                "discharge_diagnosis_system": "icd-10-cm",
            },
            "deceased": False,
        }
        facts = extract_hospital_course(record, "en")
        days = [f.hospital_day for f in facts]
        assert days == sorted(days)

    def test_surgery_event_only_when_surgical(self):
        record = {
            "encounters": [
                {"admission_datetime": "2026-03-01T09:00:00"}
            ],
            "procedures": [
                {
                    "procedure_type": "ORIF",
                    "procedure_name": "Open reduction internal fixation",
                    "category_code": "387713003",  # surgical
                    "start_datetime": "2026-03-02T10:00:00",
                    "estimated_blood_loss_ml": 300,
                },
                {
                    "procedure_type": "urinary_catheter",
                    "procedure_name": "Foley",
                    "category_code": "277132007",  # therapeutic, not surgical
                    "start_datetime": "2026-03-01T12:00:00",
                },
            ],
        }
        facts = extract_hospital_course(record, "en")
        surgery = [f for f in facts if f.event_type == "surgery"]
        assert len(surgery) == 1
        assert "Open reduction" in surgery[0].description

    def test_procedure_note_targets_invasive_bedside(self):
        assert "central_line" in _PROCEDURE_NOTE_TYPES
        assert "thoracentesis" in _PROCEDURE_NOTE_TYPES
        assert "urinary_catheter" not in _PROCEDURE_NOTE_TYPES
        assert "nasogastric_tube" not in _PROCEDURE_NOTE_TYPES


# ---------------------------------------------------------------------------
# Document generator (integration: synthetic CIF → narrative)
# ---------------------------------------------------------------------------


def _make_synthetic_cif(cif_root: Path) -> None:
    """Write a minimal valid CIF directory with 3 encounters.

    - 1 normal discharge (inpatient)
    - 1 surgical (hip fracture with ORIF)
    - 1 death
    """
    structural = cif_root / "structural" / "patients"
    structural.mkdir(parents=True, exist_ok=True)

    records = {
        "ENC-TST-001.json": _normal_discharge_record(),
        "ENC-TST-002.json": _surgery_record(),
        "ENC-TST-003.json": _death_record(),
    }
    for fn, rec in records.items():
        (structural / fn).write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _normal_discharge_record() -> dict:
    return {
        "patient": {
            "patient_id": "POP-TST-001",
            "age": 65,
            "sex": "M",
            "chronic_conditions": [{"code": "I10"}],
            "allergies": [],
            "home_medications": [],
        },
        "encounters": [
            {
                "encounter_id": "ENC-TST-001",
                "encounter_type": "inpatient",
                "status": "finished",
                "admission_datetime": "2026-03-01T09:00:00",
                "discharge_datetime": "2026-03-08T11:00:00",
                "chief_complaint": "Fever and cough",
                "attending_physician_id": "DR-IM-001",
                "admitting_physician_id": "DR-IM-001",
                "discharging_physician_id": "DR-IM-001",
                "discharge_disposition": "home",
                "department_id": "internal_medicine",
            }
        ],
        "clinical_diagnosis": {
            "admission_diagnosis_code": "J18.9",
            "admission_diagnosis_system": "icd-10-cm",
            "discharge_diagnosis_code": "J18.9",
            "discharge_diagnosis_system": "icd-10-cm",
        },
        "orders": [],
        "vital_signs": [
            {"temperature": 38.5, "heart_rate": 95, "systolic_bp": 125, "diastolic_bp": 75}
        ],
        "procedures": [],
        "complications_occurred": [],
        "deceased": False,
        "discharge_prescription": {
            "items": [
                {
                    "drug_name": "Amoxicillin",
                    "dose": "500mg",
                    "route": "PO",
                    "frequency": "BID",
                    "duration": "7 days",
                }
            ]
        },
    }


def _surgery_record() -> dict:
    rec = _normal_discharge_record()
    rec["patient"]["patient_id"] = "POP-TST-002"
    rec["encounters"][0]["encounter_id"] = "ENC-TST-002"
    rec["encounters"][0]["chief_complaint"] = "Hip pain after fall"
    rec["clinical_diagnosis"]["admission_diagnosis_code"] = "S72.0"
    rec["clinical_diagnosis"]["discharge_diagnosis_code"] = "S72.0"
    rec["procedures"] = [
        {
            "procedure_id": "PROC-POP-TST-002-001",
            "procedure_type": "ORIF",
            "procedure_name": "Open reduction internal fixation",
            "procedure_code": "27236",
            "category_code": "387713003",
            "body_site_code": "71341001",
            "outcome_code": "385669000",
            "start_datetime": "2026-03-02T10:00:00",
            "end_datetime": "2026-03-02T12:00:00",
            "primary_surgeon_id": "DR-OR-001",
            "anesthesiologist_id": "DR-AN-001",
            "anesthesia_type": "spinal",
            "asa_class": 3,
            "duration_minutes": 120,
            "estimated_blood_loss_ml": 350,
            "implants_used": ["compression hip screw"],
            "specimens_sent": [],
            "intraop_complications": [],
            "preop_diagnosis": "Right hip fracture",
            "postop_diagnosis": "Right hip fracture",
        },
        {
            "procedure_id": "PROC-POP-TST-002-002",
            "procedure_type": "central_line",
            "procedure_name": "Central venous catheter insertion",
            "procedure_code": "36556",
            "category_code": "277132007",
            "body_site_code": "113257007",
            "outcome_code": "385669000",
            "start_datetime": "2026-03-01T11:00:00",
            "end_datetime": "2026-03-01T11:45:00",
            "primary_surgeon_id": "DR-IM-001",
            "anesthesia_type": "local",
            "duration_minutes": 45,
            "intraop_complications": [],
        },
        {
            "procedure_id": "PROC-POP-TST-002-003",
            "procedure_type": "urinary_catheter",
            "procedure_name": "Foley catheter",
            "procedure_code": "51702",
            "category_code": "277132007",
            "start_datetime": "2026-03-01T10:30:00",
            "duration_minutes": 10,
        },
    ]
    return rec


def _death_record() -> dict:
    rec = _normal_discharge_record()
    rec["patient"]["patient_id"] = "POP-TST-003"
    rec["encounters"][0]["encounter_id"] = "ENC-TST-003"
    rec["encounters"][0]["discharge_disposition"] = "expired"
    rec["deceased"] = True
    rec["death_day"] = 5
    rec["complications_occurred"] = ["septic_shock"]
    return rec


def _mock_llm_service(tmp_path):
    return build_from_config(
        {
            "judgment": {"mode": "template"},
            "narrative": {
                "mode": "llm",
                "provider": "mock",
                "mock": {},
                "model_map": {"small": "mock", "medium": "mock"},
                "retry_attempts": 1,
            },
            "cache": {"enabled": False},
        }
    )


class TestDocumentGeneratorE2E:
    @pytest.fixture
    def cif_dir(self, tmp_path):
        cif = tmp_path / "cif"
        _make_synthetic_cif(cif)
        return cif

    def test_generates_all_tier_ab_documents(self, cif_dir, tmp_path):
        llm = _mock_llm_service(tmp_path)
        version = generate_documents(
            cif_dir, llm, version_id="tier_ab_test", language="en"
        )
        manifest = json.loads(
            (cif_dir / "narratives" / version / "manifest.json").read_text()
        )
        counts = manifest["document_counts_by_type"]

        # 3 inpatient encounters
        assert manifest["patient_count"] == 3
        # 3 discharge summaries, 3 admission h&p
        assert counts["discharge_summary"] == 3
        assert counts["admission_hp"] == 3
        # 1 surgery → 1 operative note
        assert counts["operative_note"] == 1
        # 1 central line in surgery record → 1 procedure note
        # (urinary_catheter is excluded as non-major)
        assert counts["procedure_note"] == 1
        # 1 death → 1 death summary
        assert counts["death_summary"] == 1

    def test_document_files_have_text_and_loinc(self, cif_dir, tmp_path):
        llm = _mock_llm_service(tmp_path)
        generate_documents(cif_dir, llm, version_id="v1", language="en")
        docs_dir = cif_dir / "narratives" / "v1" / "documents"
        assert docs_dir.is_dir()
        # Pick one discharge summary
        for enc_dir in docs_dir.iterdir():
            dc = enc_dir / "discharge_summary.json"
            if dc.exists():
                data = json.loads(dc.read_text())
                assert data["text"]
                assert data["loinc_code"] == "18842-5"
                assert data["text_source"] == "llm"
                return
        pytest.fail("No discharge summary produced")

    def test_death_summary_only_for_deceased(self, cif_dir, tmp_path):
        llm = _mock_llm_service(tmp_path)
        generate_documents(cif_dir, llm, version_id="v1", language="en")
        docs_dir = cif_dir / "narratives" / "v1" / "documents"
        death_notes = list(docs_dir.glob("*/death_summary.json"))
        assert len(death_notes) == 1
        # Only ENC-TST-003 has the death note
        assert "ENC-TST-003" in str(death_notes[0].parent)

    def test_outpatient_encounters_are_skipped(self, tmp_path):
        cif = tmp_path / "cif"
        structural = cif / "structural" / "patients"
        structural.mkdir(parents=True)
        rec = _normal_discharge_record()
        rec["encounters"][0]["encounter_type"] = "outpatient"
        (structural / "ENC-OPD-001.json").write_text(
            json.dumps(rec, ensure_ascii=False)
        )
        llm = _mock_llm_service(tmp_path)
        generate_documents(cif, llm, version_id="v1", language="en")
        manifest = json.loads((cif / "narratives" / "v1" / "manifest.json").read_text())
        assert manifest["patient_count"] == 0

    def test_in_progress_encounters_are_skipped(self, tmp_path):
        cif = tmp_path / "cif"
        structural = cif / "structural" / "patients"
        structural.mkdir(parents=True)
        rec = _normal_discharge_record()
        rec["encounters"][0]["status"] = "in-progress"
        (structural / "ENC-INPROG.json").write_text(json.dumps(rec))
        llm = _mock_llm_service(tmp_path)
        generate_documents(cif, llm, version_id="v1", language="en")
        manifest = json.loads((cif / "narratives" / "v1" / "manifest.json").read_text())
        assert manifest["patient_count"] == 0


# ---------------------------------------------------------------------------
# FHIR DocumentReference builder
# ---------------------------------------------------------------------------


class TestFHIRDocumentReferenceBuilder:
    def _sample_doc(self, **overrides) -> dict:
        base = asdict(
            ClinicalDocument(
                document_id="doc-ENC-TST-001-discharge_summary",
                task_type="discharge_summary",
                loinc_code="18842-5",
                patient_id="POP-TST-001",
                encounter_id="ENC-TST-001",
                author_practitioner_id="DR-IM-001",
                authored_datetime="2026-03-08T11:00:00",
                period_start="2026-03-01T09:00:00",
                period_end="2026-03-08T11:00:00",
                language="en",
                text="DISCHARGE SUMMARY\n\nPatient: 65yo Male\n...",
                text_source="llm",
                llm_model="mock",
                llm_input_tokens=100,
                llm_output_tokens=50,
            )
        )
        base.update(overrides)
        return base

    def test_builds_valid_fhir_resource(self):
        doc = self._sample_doc()
        r = _build_document_reference(doc, "POP-TST-001", "US")
        assert r is not None
        assert r["resourceType"] == "DocumentReference"
        assert r["id"] == "doc-ENC-TST-001-discharge_summary"
        assert r["status"] == "current"
        assert r["docStatus"] == "final"
        # Type coding
        coding = r["type"]["coding"][0]
        assert coding["system"] == "http://loinc.org"
        assert coding["code"] == "18842-5"
        # Subject reference
        assert r["subject"]["reference"] == "Patient/POP-TST-001"
        # Content
        att = r["content"][0]["attachment"]
        assert att["contentType"] == "text/plain; charset=utf-8"
        decoded = base64.b64decode(att["data"]).decode("utf-8")
        assert decoded.startswith("DISCHARGE SUMMARY")
        assert att["size"] == len(decoded.encode("utf-8"))
        # Context
        assert (
            r["context"]["encounter"][0]["reference"] == "Encounter/ENC-TST-001"
        )
        assert r["author"][0]["reference"] == "Practitioner/DR-IM-001"

    def test_empty_text_returns_none(self):
        assert _build_document_reference(self._sample_doc(text=""), "P", "US") is None

    def test_missing_loinc_returns_none(self):
        assert (
            _build_document_reference(self._sample_doc(loinc_code=""), "P", "US")
            is None
        )

    def test_operative_note_with_related_procedure(self):
        doc = self._sample_doc(
            task_type="operative_note",
            loinc_code="11504-8",
            encounter_id="ENC-TST-002",
            related_procedure_id="PROC-POP-TST-002-001",
            text="OPERATIVE NOTE ...",
        )
        r = _build_document_reference(doc, "POP-TST-002", "US")
        assert r is not None
        related = r["context"]["related"]
        # Procedure id is encounter-scoped to match Procedure.id in FHIR export
        assert related[0]["reference"] == "Procedure/ENC-TST-002-PROC-POP-TST-002-001"

    def test_template_source_sets_preliminary_docstatus(self):
        doc = self._sample_doc(text_source="template")
        r = _build_document_reference(doc, "P", "US")
        assert r["docStatus"] == "preliminary"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _discharge_summary_variables() -> dict:
    return {
        "age": 68,
        "sex": "Male",
        "admission_date": "2026-03-01",
        "discharge_date": "2026-03-08",
        "los_days": 7,
        "disposition": "home",
        "attending_physician": "Dr. Smith",
        "chief_complaint": "Fever and cough",
        "past_medical_history": ["Hypertension"],
        "admission_diagnosis": "Bacterial pneumonia",
        "discharge_diagnoses": ["Bacterial pneumonia (resolved)"],
        "hospital_course_bullets": ["Day 0: admitted", "Day 7: discharged"],
        "procedures_performed": "(none)",
        "discharge_medications": ["Amoxicillin 500mg PO BID x 7 days"],
    }
