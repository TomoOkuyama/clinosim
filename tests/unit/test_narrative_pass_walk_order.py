import json
from pathlib import Path
from typing import Any

import pytest

from clinosim.modules.document.narrative.passes import NarrativePass


def _cohort(tmp_path: Path, encounter_ids: list[str]):
    structural = tmp_path / "structural" / "patients"
    structural.mkdir(parents=True)
    for eid in encounter_ids:
        (structural / f"{eid}.json").write_text(
            json.dumps(
                {
                    "patient": {"patient_id": f"POP-{eid}", "age": 65, "sex": "M"},
                    "encounters": [{"encounter_id": eid, "encounter_type": {"value": "inpatient"}}],
                    "documents": [
                        {
                            "document_id": f"doc-{eid}-hp",
                            "task_type": "admission_hp",
                            "loinc_code": "34117-2",
                            "format_type": "composition",
                            "narrative": None,
                        },
                        {
                            "document_id": f"doc-{eid}-pn",
                            "task_type": "progress_note",
                            "loinc_code": "11506-3",
                            "format_type": "composition",
                            "narrative": None,
                        },
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


class _RecordingGenerator:
    """NarrativeGenerator stub that records (doc_type, language) call order (N-1)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def generate(self, ctx: Any, spec: Any):
        from clinosim.types.document import NarrativeOutput

        self.calls.append((spec.type_key, ctx.target_lang))
        return NarrativeOutput(raw_text="", sections={"stub": ""}, structured={}, metadata={}, facts_used=[])


class _RecordingPass(NarrativePass):
    def _generator_name(self) -> str:
        return "recording"


@pytest.mark.unit
def test_walk_order_groups_by_doc_type_then_language(tmp_path):
    """AD-65 Bedrock cache contract: same (doc_type, language) group runs contiguously."""
    _cohort(tmp_path, ["ENC-1", "ENC-2", "ENC-3"])
    gen = _RecordingGenerator()
    p = _RecordingPass(
        cif_dir=str(tmp_path), version_id="v", country="US", tasks=["admission_hp", "progress_note"], generator=gen
    )
    p.run()
    # For US country, language = "en" only → each spec is 1 group.
    # Boundaries between groups = number of unique (doc_type, lang) pairs - 1
    unique_pairs = list(dict.fromkeys(gen.calls))
    boundaries = sum(1 for a, b in zip(gen.calls, gen.calls[1:]) if a != b)
    assert boundaries == len(unique_pairs) - 1, f"walk order not grouped: calls={gen.calls}, unique={unique_pairs}"
    # Also assert group contiguity: same pair contiguous
    for pair in unique_pairs:
        indices = [i for i, c in enumerate(gen.calls) if c == pair]
        assert indices == list(range(min(indices), max(indices) + 1)), f"pair {pair} not contiguous: indices={indices}"
