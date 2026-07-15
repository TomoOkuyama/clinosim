"""Encounter YAML narrative.* field tests (Tier 1 #3 α-min-2 Task 6).

Three tests:
1. abdominal_pain_nonspecific has narrative block (priority condition, ED).
2. All 46 encounter YAMLs have narrative block (forward-coverage gate).
3. Encounter type matches narrative sub-block:
   - outpatient encounters have outpatient_soap_template
   - emergency encounters have ed_note_template + ed_triage_template

Loader: load_encounter_condition() returns dict, so we check via parsed dict
or via EncounterConditionProtocol.narrative Pydantic field.
"""

from __future__ import annotations

import os

from clinosim.modules.encounter.protocol import (
    EncounterConditionProtocol,
    load_encounter_condition,
)

_ENCOUNTER_DIR = os.path.join(
    os.path.dirname(__file__),
    "../../../../clinosim/modules/encounter/reference_data",
)


def test_abdominal_pain_nonspecific_has_narrative_block() -> None:
    """abdominal_pain_nonspecific (priority ED encounter) must have narrative populated."""
    raw = load_encounter_condition("abdominal_pain_nonspecific")
    p = EncounterConditionProtocol.model_validate(raw)
    assert p.narrative is not None, "narrative block missing in abdominal_pain_nonspecific"
    assert p.narrative.ed_note_template is not None, "ed_note_template missing (ED encounter)"
    assert p.narrative.ed_note_template.chief_complaint_ja, "chief_complaint_ja empty"
    assert p.narrative.ed_note_template.hpi_ja, "hpi_ja empty"
    assert p.narrative.ed_triage_template is not None, "ed_triage_template missing (ED encounter)"
    assert p.narrative.ed_triage_template.common_triage_levels, "common_triage_levels empty"


def test_all_46_encounters_have_narrative() -> None:
    """Forward-coverage gate: every encounter YAML must have a narrative block."""
    yaml_files = sorted(f for f in os.listdir(_ENCOUNTER_DIR) if f.endswith(".yaml"))
    assert yaml_files, "No encounter YAML files found — check path"

    missing: list[str] = []
    for yf in yaml_files:
        cid = yf.replace(".yaml", "")
        raw = load_encounter_condition(cid)
        p = EncounterConditionProtocol.model_validate(raw)
        if p.narrative is None:
            missing.append(cid)

    assert not missing, f"{len(missing)} encounter(s) missing narrative block: {missing}"


def test_encounter_narrative_type_matches_encounter_type() -> None:
    """outpatient encounters have outpatient_soap_template; ED encounters have ed_note_template."""
    yaml_files = sorted(f for f in os.listdir(_ENCOUNTER_DIR) if f.endswith(".yaml"))

    outpatient_wrong: list[str] = []
    ed_wrong: list[str] = []

    for yf in yaml_files:
        cid = yf.replace(".yaml", "")
        raw = load_encounter_condition(cid)
        p = EncounterConditionProtocol.model_validate(raw)
        enc_type = raw.get("encounter_type", "")

        if p.narrative is None:
            continue  # caught by forward-coverage test above

        if enc_type == "outpatient":
            if p.narrative.outpatient_soap_template is None:
                outpatient_wrong.append(cid)
        elif enc_type.startswith("emergency"):
            if p.narrative.ed_note_template is None:
                ed_wrong.append(cid)

    assert not outpatient_wrong, f"outpatient encounters missing outpatient_soap_template: {outpatient_wrong}"
    assert not ed_wrong, f"ED encounters missing ed_note_template: {ed_wrong}"
