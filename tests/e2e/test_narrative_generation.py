"""E2E test for Stage 2 narrative generation."""

import json
import os

import pytest

from clinosim.modules.llm_service.engine import LLMService
from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.narrative_generator import generate_narratives
from clinosim.simulator_beta import run_alpha
from clinosim.types.config import SimulatorConfig


@pytest.fixture(scope="module")
def cif_dir(tmp_path_factory):
    """Generate structural CIF for narrative testing."""
    d = str(tmp_path_factory.mktemp("cif"))
    dataset = run_alpha(SimulatorConfig(random_seed=42))
    write_cif(dataset, d)
    return d


@pytest.mark.e2e
class TestNarrativeGeneration:
    def test_template_mode_generates_narratives(self, cif_dir):
        llm = LLMService(mode="template")
        version = generate_narratives(cif_dir, llm, version_id="test_template", language="ja")

        narrative_dir = os.path.join(cif_dir, "narratives", version, "patients")
        assert os.path.exists(narrative_dir)

        files = os.listdir(narrative_dir)
        assert len(files) == 1  # alpha: 1 patient

        with open(os.path.join(narrative_dir, files[0])) as f:
            data = json.load(f)

        assert data["patient_id"] == "FORCED-0001"
        assert len(data["notes"]) >= 4  # H&P + progress notes + discharge

        # Check note types present
        note_types = {n["note_type"] for n in data["notes"]}
        assert "admission_hp" in note_types
        assert "progress_note" in note_types
        assert "discharge_summary" in note_types

    def test_manifest_created(self, cif_dir):
        llm = LLMService(mode="template")
        version = generate_narratives(cif_dir, llm, version_id="test_manifest", language="ja")

        manifest_path = os.path.join(cif_dir, "narratives", version, "manifest.json")
        assert os.path.exists(manifest_path)

        with open(manifest_path) as f:
            manifest = json.load(f)
        assert manifest["patient_count"] == 1
        assert manifest["language"] == "ja"

    def test_current_version_tracking(self, cif_dir):
        llm = LLMService(mode="template")
        generate_narratives(cif_dir, llm, version_id="v1_test", language="ja")
        generate_narratives(cif_dir, llm, version_id="v2_test", language="ja")

        current_path = os.path.join(cif_dir, "narratives", "current_version.txt")
        with open(current_path) as f:
            current = f.read().strip()
        assert current == "v2_test"  # latest version is current

    def test_japanese_narratives_contain_japanese(self, cif_dir):
        llm = LLMService(mode="template")
        version = generate_narratives(cif_dir, llm, version_id="test_ja", language="ja")

        narrative_dir = os.path.join(cif_dir, "narratives", version, "patients")
        files = os.listdir(narrative_dir)
        with open(os.path.join(narrative_dir, files[0])) as f:
            data = json.load(f)

        hp_note = next(n for n in data["notes"] if n["note_type"] == "admission_hp")
        assert "入院時記録" in hp_note["text"] or "主訴" in hp_note["text"]
