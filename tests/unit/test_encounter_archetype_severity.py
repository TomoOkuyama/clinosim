"""β-JP-1 chain 1a T1 (spec §2a): Stage 1 persistence of clinical_course_archetype
+ severity on Encounter.

Pins:
  - Encounter dataclass carries `clinical_course_archetype` (default "" =
    backward-compat with pre-1a CIF JSON).
  - The inpatient simulator writes both the selected archetype and severity
    onto the Encounter record.
  - CIF write → JSON round-trip preserves both fields.
  - Old structural JSON without the new key still loads (dict read path).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.modules.output.cif_writer import write_cif
from clinosim.simulator import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig
from clinosim.types.encounter import Encounter

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def forced_dataset():
    scenario = ForcedScenario(
        disease_id="bacterial_pneumonia",
        count=1,
        severity="severe",
        archetype="treatment_resistant",
    )
    config = SimulatorConfig(random_seed=42, country="US")
    return run_forced(scenario, config)


def test_encounter_dataclass_has_archetype_default_empty():
    enc = Encounter()
    assert enc.clinical_course_archetype == ""


def test_inpatient_simulator_persists_archetype_and_severity(forced_dataset):
    enc = forced_dataset.patients[0].encounters[0]
    assert enc.severity == "severe"
    assert enc.clinical_course_archetype == "treatment_resistant"


def test_cif_write_read_round_trip(forced_dataset, tmp_path: Path):
    write_cif(forced_dataset, str(tmp_path))
    patients_dir = tmp_path / "structural" / "patients"
    files = sorted(patients_dir.glob("*.json"))
    assert files, "expected at least one structural patient JSON"
    record = json.loads(files[0].read_text())
    enc = record["encounters"][0]
    assert enc["severity"] == "severe"
    assert enc["clinical_course_archetype"] == "treatment_resistant"


def test_old_json_without_archetype_field_still_loads():
    """Pre-1a structural JSON has no clinical_course_archetype key — the dict
    read path (CIFReader / NarrativePass) must default cleanly."""
    old_enc = {"encounter_id": "ENC-1", "encounter_type": "inpatient"}
    # dict read path convention used across Stage 2 / FHIR builders
    assert old_enc.get("clinical_course_archetype", "") == ""
    assert old_enc.get("severity", "") == ""


def test_run_daily_loop_passes_real_severity_to_evaluate_complications(monkeypatch):
    """Before this fix, _run_daily_loop ignored its own accurate `severity`
    parameter and re-derived a separate, less-accurate `severity_str` via
    target_los-mean matching, which is what actually reached
    evaluate_complications. This pins that the real, forced severity is what
    gets passed."""
    from clinosim.simulator import inpatient as inpatient_mod

    captured: dict = {}
    original = inpatient_mod.evaluate_complications

    def spy(*args, **kwargs):
        captured["kwargs"] = kwargs
        return original(*args, **kwargs)

    monkeypatch.setattr(inpatient_mod, "evaluate_complications", spy)

    scenario = ForcedScenario(disease_id="bacterial_pneumonia", count=1, severity="severe")
    config = SimulatorConfig(random_seed=42, country="US")
    run_forced(scenario, config)

    assert captured, (
        "evaluate_complications was never called (check target_los >= 2 and complications are non-empty for bacterial_pneumonia/severe/US)"  # noqa: E501
    )  # noqa: E501
    assert captured["kwargs"].get("severity") == "severe"


def test_select_archetype_receives_disease_course_archetypes(monkeypatch):
    """Before this fix, _simulate_patient's natural (non-forced) archetype
    draw called select_archetype() without protocol_archetypes, so every
    disease used the generic _FALLBACK_PROBABILITIES table regardless of its
    own YAML-authored course_archetypes. A sibling call site 470 lines later
    (get_daily_directive) already passed this correctly."""
    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.simulator import inpatient as inpatient_mod

    captured: dict = {}
    original = inpatient_mod.select_archetype

    def spy(*args, **kwargs):
        captured["kwargs"] = kwargs
        return original(*args, **kwargs)

    monkeypatch.setattr(inpatient_mod, "select_archetype", spy)

    scenario = ForcedScenario(disease_id="bacterial_pneumonia", count=1, severity="moderate")
    config = SimulatorConfig(random_seed=42, country="US")
    run_forced(scenario, config)

    protocol = load_disease_protocol("bacterial_pneumonia")
    assert captured.get("kwargs", {}).get("protocol_archetypes") == protocol.course_archetypes
