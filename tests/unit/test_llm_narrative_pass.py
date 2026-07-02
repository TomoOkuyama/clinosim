"""Tests for LLMNarrativePass (N-1b, N-chain narrative IF unification).

Bridge pin: MockProvider → LLMService → LLMNarrativePass → narratives/<version>/
round-trip. Uses the PRODUCTION document_type_specs.yaml, where admission_hp
carries stage2_strategy=template_seed + llm_enabled_sections=[hpi,
assessment_and_plan] — the seam is proven without touching YAML.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.modules.document.narrative.passes import (
    LLMNarrativePass,
    TemplateNarrativePass,
)
from clinosim.modules.llm_service.engine import LLMService
from clinosim.modules.llm_service.providers import MockProvider


def _write_tiny_structural(tmp_path: Path) -> Path:
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    payload = {
        "patient": {"patient_id": "POP-1", "age": 65, "sex": "M",
                    "chronic_conditions": []},
        "encounters": [{"encounter_id": "ENC-1",
                        "encounter_type": {"value": "inpatient"},
                        "attending_physician_id": "DR-1"}],
        "documents": [
            {"document_id": "doc-1", "task_type": "admission_hp",
             "loinc_code": "34117-2", "format_type": "composition",
             "narrative": None},
            {"document_id": "doc-2", "task_type": "progress_note",
             "loinc_code": "11506-3", "format_type": "free_text",
             "narrative": None},
        ],
        "vitals": [], "lab_results": [], "medications": [], "diagnoses": [],
        "procedures": [], "allergies": [],
    }
    (structural / "ENC-1.json").write_text(json.dumps(payload, ensure_ascii=False))
    return tmp_path


def _mock_llm() -> LLMService:
    return LLMService(
        mode="llm",
        narrative_provider=MockProvider(),
        narrative_model_map={"medium": "mock"},
        provider_name_narrative="mock",
        retry_attempts=1,
        retry_backoff_seconds=0.0,
    )


@pytest.mark.unit
def test_llm_pass_writes_narratives_with_llm_generator_name(tmp_path):
    _write_tiny_structural(tmp_path)
    manifest = LLMNarrativePass(
        cif_dir=str(tmp_path), llm=_mock_llm(), version_id="llmtest", country="US"
    ).run()
    assert manifest.generator == "llm-mock"
    assert manifest.document_count >= 2
    assert (tmp_path / "narratives/llmtest/documents/ENC-1/doc-1.json").exists()
    assert (tmp_path / "narratives/llmtest/documents/ENC-1/doc-2.json").exists()


@pytest.mark.unit
def test_llm_pass_manifest_carries_cost_report(tmp_path):
    _write_tiny_structural(tmp_path)
    manifest = LLMNarrativePass(
        cif_dir=str(tmp_path), llm=_mock_llm(), version_id="llmtest", country="US"
    ).run()
    report = manifest.llm_cost_report
    assert report["total_calls"] >= 1  # admission_hp has 2 llm_enabled_sections
    assert report["total_input_tokens"] > 0
    assert report["total_output_tokens"] > 0
    # Persisted in manifest.json too
    m = json.loads((tmp_path / "narratives/llmtest/manifest.json").read_text())
    assert m["llm_cost_report"]["total_calls"] >= 1


@pytest.mark.unit
def test_llm_pass_replaces_only_llm_enabled_sections(tmp_path, tmp_path_factory):
    """template_seed seam pin on the production admission_hp spec:
    hpi + assessment_and_plan replaced by LLM text; the other 7 sections,
    facts_used and raw_text identical to the template pass output.
    progress_note (template_only) is byte-identical modulo generator label.
    """
    _write_tiny_structural(tmp_path)
    tmp2 = tmp_path_factory.mktemp("template_run")
    _write_tiny_structural(tmp2)

    TemplateNarrativePass(cif_dir=str(tmp2), country="US", rng_seed=42).run()
    LLMNarrativePass(cif_dir=str(tmp_path), llm=_mock_llm(),
                     version_id="llmtest", country="US", rng_seed=42).run()

    tpl = json.loads(
        (tmp2 / "narratives/template/documents/ENC-1/doc-1.json").read_text()
    )["narrative"]
    llm = json.loads(
        (tmp_path / "narratives/llmtest/documents/ENC-1/doc-1.json").read_text()
    )["narrative"]

    # LLM-enabled sections replaced
    for section in ("hpi", "assessment_and_plan"):
        assert llm["sections"][section].startswith("[Mock LLM response"), section
        assert llm["sections"][section] != tpl["sections"][section]
    # All other sections byte-identical to the template output
    for section, text in tpl["sections"].items():
        if section in ("hpi", "assessment_and_plan"):
            continue
        assert llm["sections"][section] == text, section
    # raw_text (unmodified template base) + facts_used unchanged
    assert llm["text"] == tpl["text"]
    assert llm["facts_used"] == tpl["facts_used"]
    assert llm["generator"] == "llm-mock"

    # template_only spec (progress_note): content identical, no LLM injection
    tpl_pn = json.loads(
        (tmp2 / "narratives/template/documents/ENC-1/doc-2.json").read_text()
    )["narrative"]
    llm_pn = json.loads(
        (tmp_path / "narratives/llmtest/documents/ENC-1/doc-2.json").read_text()
    )["narrative"]
    assert llm_pn["text"] == tpl_pn["text"]
    assert llm_pn["sections"] == tpl_pn["sections"]


@pytest.mark.unit
def test_template_pass_manifest_cost_report_stays_empty(tmp_path):
    """Template path byte-identity guard: no llm_cost_report leakage."""
    _write_tiny_structural(tmp_path)
    manifest = TemplateNarrativePass(cif_dir=str(tmp_path), country="US").run()
    assert manifest.llm_cost_report == {}
