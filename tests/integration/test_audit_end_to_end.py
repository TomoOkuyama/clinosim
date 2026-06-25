"""End-to-end: engine + reporter on a minimal synthetic cohort."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from clinosim.audit.engine import AuditEngine
from clinosim.audit.registry import _reset_for_test
from clinosim.audit.reporter import write_markdown


@pytest.fixture(autouse=True)
def _reset():
    _reset_for_test()
    importlib.reload(importlib.import_module("clinosim.modules.hai.audit"))
    yield
    _reset_for_test()


def _write(path: Path, country: str, file: str, rows: list[dict]):
    p = path / country / "fhir_r4" / file
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


@pytest.mark.integration
def test_end_to_end_minimal_cohort_full_report(tmp_path: Path):
    # A tiny US cohort: 2 inpatient encounters with WBC + CRP, no HAI
    _write(tmp_path, "us", "Encounter.ndjson", [
        {"resourceType": "Encounter", "id": "E1", "class": {"code": "IMP"}},
        {"resourceType": "Encounter", "id": "E2", "class": {"code": "IMP"}},
    ])
    _write(tmp_path, "us", "Observation.ndjson", [
        {
            "resourceType": "Observation", "id": "o-1",
            "code": {"coding": [{"code": "6690-2", "display": "WBC"}]},
            "encounter": {"reference": "Encounter/E1"},
            "valueQuantity": {"value": 12000},
            "referenceRange": [{}], "interpretation": [{}],
        },
        {
            "resourceType": "Observation", "id": "o-2",
            "code": {"coding": [{"code": "1988-5", "display": "CRP"}]},
            "encounter": {"reference": "Encounter/E1"},
            "valueQuantity": {"value": 25},
            "referenceRange": [{}], "interpretation": [{}],
        },
    ])

    engine = AuditEngine(cohort_dir=tmp_path)
    result = engine.run()

    # No HAI events → silent_no_op PASS, clinical WARN (rare-event)
    assert result.overall_status() in ("PASS", "WARN")
    assert ("structural", "hai") in result.results
    assert ("silent_no_op", "hai") in result.results

    # Reporter writes a complete file
    out = tmp_path / "report.md"
    write_markdown(result, out)
    text = out.read_text(encoding="utf-8")
    assert "## Summary" in text
    assert "hai" in text
