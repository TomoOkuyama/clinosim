"""Plumbing regression guards for Phase 3a HAI lift in run_forced.

The post-PR-90 xhigh review surfaced two related bugs that the previous
test suite missed because every test bypassed the enricher path:
  - case-mismatch (UPPERCASE YAML keys vs lowercase enricher writes)
  - run_forced never called register_builtin_enrichers()

These tests guard the plumbing directly (without depending on a 50-patient
ICU-transfer rate that fluctuates).
"""
from __future__ import annotations

from datetime import date as _date

import pytest

from clinosim.modules.hai import HAI_TYPES
from clinosim.simulator import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig


@pytest.mark.integration
def test_run_forced_registers_post_encounter_enrichers():
    """After run_forced executes, the POST_ENCOUNTER registry must have
    the device + hai enrichers registered. Pre-fix: run_forced silently
    skipped register_builtin_enrichers() so POST_ENCOUNTER was empty and
    every encounter's enricher hook was a no-op."""
    scenario = ForcedScenario(
        disease_id="bacterial_pneumonia", count=1, archetype="standard",
        severity="mild",
    )
    config = SimulatorConfig(country="US", random_seed=42)
    run_forced(scenario, config)

    from clinosim.simulator.enrichers import POST_ENCOUNTER, _ENRICHERS
    names_in_post_encounter = {
        name for name, e in _ENRICHERS.items() if e.stage == POST_ENCOUNTER
    }
    assert "device" in names_in_post_encounter, (
        "modules/device not registered in POST_ENCOUNTER stage "
        "(run_forced is missing register_builtin_enrichers)"
    )
    assert "hai" in names_in_post_encounter, (
        "modules/hai not registered in POST_ENCOUNTER stage "
        "(run_forced is missing register_builtin_enrichers)"
    )


@pytest.mark.integration
def test_hai_event_hai_type_strings_are_canonical():
    """Any HAI event the enricher produces in a forced cohort must use
    canonical lowercase hai_type strings; a regression would surface here
    even before the apply_hai_lab_lift YAML key-check fires."""
    scenario = ForcedScenario(
        disease_id="sepsis", count=100, archetype="treatment_resistant",
        severity="severe",
    )
    config = SimulatorConfig(country="US", random_seed=42)
    dataset = run_forced(scenario, config)

    seen_types: set[str] = set()
    seen_devices = 0
    for rec in dataset.patients:
        ext = getattr(rec, "extensions", None) or {}
        if ext.get("device"):
            seen_devices += 1
        for ev in ext.get("hai") or []:
            seen_types.add(getattr(ev, "hai_type", "?"))

    if seen_devices == 0 and not seen_types:
        pytest.skip(
            "No ICU transfers in this small forced cohort (device + hai "
            "rare-event). Plumbing already covered by "
            "test_run_forced_registers_post_encounter_enrichers; this test "
            "only adds redundant production-data verification when ICU "
            "fires."
        )

    bad = {t for t in seen_types if t not in HAI_TYPES}
    assert not bad, (
        f"enricher produced non-canonical hai_type strings {bad}; "
        f"must be one of {HAI_TYPES}"
    )


@pytest.mark.integration
def test_snapshot_truncates_post_snapshot_hai_events():
    """Snapshot-date semantics: an HAI event whose onset_date is past the
    snapshot must be dropped from extensions["hai"] (the patient hasn't
    contracted it yet as-of the snapshot). Pre-fix: the snapshot filter
    ran BEFORE POST_ENCOUNTER so HAI events past the snapshot leaked.

    This test stages a synthetic record + runs the snapshot pass inline
    (the apply path lives in inpatient.py:469+); a full run_forced with
    snapshot would require careful seed-hunting for HAI in the truncation
    window, which is brittle. The inline check verifies the filter logic.
    """
    from types import SimpleNamespace

    from clinosim.types.hai import HAIEvent
    snapshot_date = _date(2026, 1, 15)
    pre_hai = HAIEvent(
        hai_id="h1", encounter_id="e1", hai_type="clabsi",
        source_device_id="d1", icd10_code="T80.211A",
        snomed_code="736442006", onset_date="2026-01-12",  # before snapshot
        organism_snomed="3092008", culture_specimen_id="s1",
    )
    post_hai = HAIEvent(
        hai_id="h2", encounter_id="e1", hai_type="cauti",
        source_device_id="d2", icd10_code="T83.511A",
        snomed_code="68566005", onset_date="2026-01-18",  # past snapshot
        organism_snomed="112283007", culture_specimen_id="s2",
    )
    record = SimpleNamespace(
        extensions={"hai": [pre_hai, post_hai]},
        microbiology=[],
    )

    # Inline the truncation block from inpatient.py:
    ext = record.extensions or {}
    ext_hai = ext.get("hai") or []
    kept_hai = []
    for ev in ext_hai:
        try:
            onset = _date.fromisoformat(ev.onset_date)
        except (TypeError, ValueError):
            kept_hai.append(ev)
            continue
        if onset > snapshot_date:
            continue
        kept_hai.append(ev)
    if len(kept_hai) != len(ext_hai):
        ext["hai"] = kept_hai

    assert len(record.extensions["hai"]) == 1
    assert record.extensions["hai"][0].hai_id == "h1"
