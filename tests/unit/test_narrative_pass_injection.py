"""N-1 generator contract + injection tests (N-chain narrative IF unification).

Pins:
- NarrativePass owns the generator (constructor injection); a custom
  NarrativeGenerator stub flows through run() end-to-end.
- TemplateNarrativePass(generator=None) defaults to TemplateNarrativeGenerator.
- DocumentTypeSpec is importable from clinosim.types.document (types rule)
  AND from its historical home clinosim.modules.document.narrative.registry
  (backwards-compat re-export).
- NarrativeGenerator Protocol is runtime_checkable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.modules.document.narrative.passes import NarrativePass, TemplateNarrativePass
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import (
    DocumentTypeSpec,
    NarrativeContext,
    NarrativeGenerator,
    NarrativeOutput,
)


def _write_tiny_structural(tmp_path: Path) -> Path:
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    payload = {
        "patient": {"patient_id": "POP-1", "age": 65, "sex": "M", "chronic_conditions": []},
        "encounters": [
            {"encounter_id": "ENC-1", "encounter_type": {"value": "inpatient"}, "attending_physician_id": "DR-1"}
        ],
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
    (structural / "ENC-1.json").write_text(json.dumps(payload, ensure_ascii=False))
    return tmp_path


class _StubGenerator:
    """Minimal NarrativeGenerator stub (structural typing, no inheritance)."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        self.calls += 1
        return NarrativeOutput(
            raw_text="STUB TEXT",
            sections={"hpi": "STUB SECTION"},
            metadata={"generator": "stub"},
            facts_used=["stub.fact"],
        )


class _StubPass(NarrativePass):
    """Concrete pass exercising base-class _generate via injected generator."""

    def _generator_name(self) -> str:
        return "stub"


@pytest.mark.unit
def test_narrative_generator_protocol_runtime_checkable() -> None:
    assert isinstance(_StubGenerator(), NarrativeGenerator)
    assert isinstance(TemplateNarrativeGenerator(), NarrativeGenerator)


@pytest.mark.unit
def test_document_type_spec_importable_from_both_homes() -> None:
    from clinosim.modules.document.narrative.registry import (
        DocumentTypeSpec as RegistrySpec,
    )

    assert RegistrySpec is DocumentTypeSpec


@pytest.mark.unit
def test_injected_generator_flows_through_run(tmp_path: Path) -> None:
    """A custom generator injected into the pass produces the narrative content."""
    _write_tiny_structural(tmp_path)
    stub = _StubGenerator()
    p = _StubPass(
        cif_dir=str(tmp_path),
        version_id="stubtest",
        country="US",
        generator=stub,
    )
    manifest = p.run()
    assert stub.calls >= 1
    assert manifest.generator == "stub"
    payload = json.loads((tmp_path / "narratives/stubtest/documents/ENC-1/doc-1.json").read_text())
    assert payload["narrative"]["text"] == "STUB TEXT"
    assert payload["narrative"]["sections"] == {"hpi": "STUB SECTION"}
    assert payload["narrative"]["generator"] == "stub"


@pytest.mark.unit
def test_template_pass_default_generator_is_template(tmp_path: Path) -> None:
    p = TemplateNarrativePass(cif_dir=str(tmp_path))
    assert isinstance(p.generator, TemplateNarrativeGenerator)


@pytest.mark.unit
def test_template_pass_accepts_injected_generator(tmp_path: Path) -> None:
    _write_tiny_structural(tmp_path)
    stub = _StubGenerator()
    p = TemplateNarrativePass(cif_dir=str(tmp_path), generator=stub)
    p.run()
    assert stub.calls >= 1
