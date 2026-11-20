"""Disease YAML narrative.* field tests (Tier 1 #3 α-min-1 Task 4).

Three tests:
1. bacterial_pneumonia has narrative block with expected sub-fields.
2. No course archetype carries authored daily S/O/A/P narrative text (Issue #3400).
3. Forward-coverage gate: ALL disease YAMLs (32) must have narrative block.

Note: The brief referenced "30 diseases" but the reference_data directory
contains 32 YAML files as of Tier 1 #3 implementation.  The gate tests all
files present so it automatically covers future additions.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from clinosim.modules.disease.protocol import load_disease_protocol


def test_bacterial_pneumonia_has_narrative_block() -> None:
    """bacterial_pneumonia must have all three narrative sub-fields populated."""
    p = load_disease_protocol("bacterial_pneumonia")
    assert p.narrative is not None, "narrative block missing"
    assert p.narrative.hpi_template, "hpi_template empty"
    assert p.narrative.hpi_template.onset_pattern, "onset_pattern empty"
    assert p.narrative.physical_exam_findings, "physical_exam_findings empty"
    assert p.narrative.discharge_instructions, "discharge_instructions empty"
    assert p.narrative.discharge_instructions.follow_up, "follow_up empty"
    assert p.narrative.discharge_instructions.emergency, "emergency empty"


def test_no_course_archetype_carries_authored_daily_narrative() -> None:
    """No disease YAML course archetype may carry authored S/O/A/P text (Issue #3400).

    The same generic strings (symptom relief, good treatment response, improved
    findings, continue treatment) used to sit on one archetype of 23 diseases. In
    Japanese progress notes they replaced the whole day's Subjective / Assessment /
    Plan, dropping complications, the lab course, medications and diet, and asserted
    improvement regardless of the day's data. The notes compose those sections from
    the record instead (as English notes always did), so a ``daily_trajectory`` that
    carries subjective / objective / assessment / plan text would override the
    composers again. Real per-day text must be authored as a composer rule, not here.
    """
    disease_dir = Path("clinosim/modules/disease/reference_data")
    offenders = []
    for path in sorted(disease_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for arch_id, arch in (data.get("course_archetypes") or {}).items():
            for day, entry in ((arch or {}).get("daily_trajectory") or {}).items():
                for key in ("subjective", "objective", "assessment", "plan"):
                    if (entry or {}).get(key):
                        offenders.append(f"{path.name}:{arch_id}:{day}:{key}")
    assert not offenders, offenders


def test_all_diseases_have_narrative() -> None:
    """Forward-coverage gate: every disease YAML must have a narrative block.

    This ensures Task 6 (TemplateNarrativeGenerator) can emit narratives for
    any disease without silent fallback to generic boilerplate.
    """
    disease_dir = "clinosim/modules/disease/reference_data"
    yaml_files = [f for f in os.listdir(disease_dir) if f.endswith(".yaml")]
    assert yaml_files, "No disease YAML files found — check the path"

    missing: list[str] = []
    for yf in sorted(yaml_files):
        name = yf.replace(".yaml", "")
        p = load_disease_protocol(name)
        if p.narrative is None:
            missing.append(name)

    assert not missing, f"{len(missing)} disease(s) missing narrative block: {missing}"
