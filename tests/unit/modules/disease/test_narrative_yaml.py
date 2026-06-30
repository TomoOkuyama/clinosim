"""Disease YAML narrative.* field tests (Tier 1 #3 α-min-1 Task 4).

Three tests:
1. bacterial_pneumonia has narrative block with expected sub-fields.
2. bacterial_pneumonia smooth_recovery archetype has daily_trajectory with SOAP entries.
3. Forward-coverage gate: ALL disease YAMLs (32) must have narrative block.

Note: The brief referenced "30 diseases" but the reference_data directory
contains 32 YAML files as of Tier 1 #3 implementation.  The gate tests all
files present so it automatically covers future additions.
"""

from __future__ import annotations

import os

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


def test_bacterial_pneumonia_archetype_has_daily_trajectory() -> None:
    """smooth_recovery archetype in bacterial_pneumonia must have daily_trajectory.

    Note: course_archetypes is typed as dict[str, Any] in DiseaseProtocol to
    preserve dict-style access used throughout the simulator (inpatient.py, etc.).
    daily_trajectory is stored as a plain nested dict inside the archetype dict.
    """
    p = load_disease_protocol("bacterial_pneumonia")
    arch = p.course_archetypes.get("smooth_recovery")
    assert arch is not None, "smooth_recovery archetype missing"
    assert "daily_trajectory" in arch, "daily_trajectory missing in smooth_recovery"
    dt = arch["daily_trajectory"]
    assert "day_0" in dt, "day_0 missing in daily_trajectory"
    assert "subjective" in dt["day_0"], "subjective missing in day_0"
    assert dt["day_0"]["subjective"], "subjective is empty in day_0"
    assert "objective" in dt["day_0"], "objective missing in day_0"
    assert "assessment" in dt["day_0"], "assessment missing in day_0"
    assert "plan" in dt["day_0"], "plan missing in day_0"


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

    assert not missing, (
        f"{len(missing)} disease(s) missing narrative block: {missing}"
    )
