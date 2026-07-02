"""Integration: generate (structural CIF) → narrate --provider mock (N-chain).

Bridge proof for the unified narrative interface over a REAL generated cohort:
- `narrate --provider mock --version-id llmtest` writes narratives/llmtest/
  through LLMNarrativePass → LLMNarrativeGenerator → LLMService(MockProvider).
- Sections are LLM-replaced ONLY for specs with stage2_strategy=template_seed
  + non-empty llm_enabled_sections (production YAML: admission_hp +
  discharge_summary); every other spec/section stays byte-identical to the
  template pass output.
- Re-running `narrate --provider template` after the mock run reproduces the
  auto-generated template narratives byte-identically (template path
  unaffected by the N-chain wiring).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

LLM_SEED_SECTIONS = {
    "admission_hp": {"hpi", "assessment_and_plan"},
    "discharge_summary": {"hospital_course", "discharge_instructions"},
}


def _run_cli(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", *argv],
        capture_output=True,
        text=True,
    )


def _load_narratives(cif_dir: Path, version: str) -> dict[str, dict]:
    """Return {"<enc>/<doc>.json": narrative payload} for a version dir."""
    docs_dir = cif_dir / "narratives" / version / "documents"
    result: dict[str, dict] = {}
    for f in sorted(docs_dir.rglob("*.json")):
        result[f"{f.parent.name}/{f.name}"] = json.loads(f.read_text())
    return result


def _task_type_by_document_id(cif_dir: Path) -> dict[str, str]:
    """Map document_id -> task_type from the structural CIF document stubs."""
    mapping: dict[str, str] = {}
    for pf in (cif_dir / "structural" / "patients").glob("*.json"):
        patient = json.loads(pf.read_text())
        for doc in patient.get("documents") or []:
            mapping[doc["document_id"]] = doc.get("task_type", "")
    return mapping


@pytest.mark.integration
def test_narrate_mock_over_generated_cif() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        r = _run_cli(
            "generate", "--country", "US", "--population", "60",
            "--seed", "42", "--format", "cif", "--output", str(out),
        )
        assert r.returncode == 0, r.stderr
        cif_dir = out / "cif"
        template_before = _load_narratives(cif_dir, "template")
        assert template_before, "generate did not auto-run the template pass"

        # --- mock LLM pass over the same structural CIF ---
        r = _run_cli(
            "narrate", "--cif-dir", str(cif_dir), "--provider", "mock",
            "--version-id", "llmtest", "--country", "US", "--no-set-current",
        )
        assert r.returncode == 0, r.stderr
        llm = _load_narratives(cif_dir, "llmtest")
        assert set(llm.keys()) == set(template_before.keys()), (
            "mock pass must cover exactly the same documents as the template pass"
        )

        manifest = json.loads(
            (cif_dir / "narratives" / "llmtest" / "manifest.json").read_text()
        )
        assert manifest["generator"] == "llm-mock"
        assert manifest["llm_cost_report"]["total_calls"] >= 1

        task_types = _task_type_by_document_id(cif_dir)
        replaced = 0
        for key, tpl_payload in template_before.items():
            tpl = tpl_payload["narrative"]
            new = llm[key]["narrative"]
            task_type = task_types[tpl_payload["document_id"]]
            seed_sections = LLM_SEED_SECTIONS.get(task_type)
            assert new["text"] == tpl["text"], f"raw_text drifted: {key}"
            assert new["facts_used"] == tpl["facts_used"], f"facts_used drifted: {key}"
            if seed_sections is None:
                # template_only spec: sections byte-identical
                assert new["sections"] == tpl["sections"], f"unexpected replacement: {key}"
                continue
            for section, text in tpl["sections"].items():
                if section in seed_sections:
                    assert new["sections"][section].startswith("[Mock LLM response"), (
                        f"section not LLM-replaced: {key}#{section}"
                    )
                    replaced += 1
                else:
                    assert new["sections"][section] == text, (
                        f"non-enabled section drifted: {key}#{section}"
                    )
        assert replaced >= 1, "no template_seed section was replaced — seam is dead"

        # --- template pass re-run must be byte-identical (path unaffected) ---
        r = _run_cli(
            "narrate", "--cif-dir", str(cif_dir), "--provider", "template",
            "--version-id", "template_rerun", "--country", "US", "--no-set-current",
        )
        assert r.returncode == 0, r.stderr
        template_after = _load_narratives(cif_dir, "template_rerun")
        assert template_after == template_before, (
            "template provider output changed after N-chain wiring"
        )
