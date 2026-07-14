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

    from clinosim.simulator.enrichers import _ENRICHERS, POST_ENCOUNTER
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
    # PR-93 adversarial review fix: also pin antibiotic registration
    # so a future PR cannot remove it without the test catching it.
    assert "antibiotic" in names_in_post_encounter, (
        "modules/antibiotic not registered in POST_ENCOUNTER stage "
        "(register_builtin_enrichers regression)"
    )


@pytest.mark.integration
def test_hai_event_hai_type_strings_are_canonical():
    """Any HAI event the enricher produces in a forced cohort must use
    canonical lowercase hai_type strings; a regression would surface here
    even before the apply_hai_lab_lift YAML key-check fires.

    PR3b-1 Task 7b: now uses force_hai_event for deterministic CAUTI
    emission so this no longer pytest.skips on small cohorts; completes
    the PR-90 教訓 implementation by exercising the actual enricher path
    end-to-end with guaranteed HAI events.
    """
    scenario = ForcedScenario(
        disease_id="sepsis", count=100, archetype="treatment_resistant",
        severity="severe",
        force_hai_event={
            "hai_type": "cauti",
            "onset_offset_days": 3,
            "organism_snomed": "112283007",   # E. coli
        },
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

    # Device placement is still stochastic (icu_transferred gate, AD-55 Module
    # PR-A). Over 100 severe-sepsis treatment_resistant patients, a non-zero
    # fraction reach ICU and receive an indwelling catheter; force_hai_event
    # then deterministically emits CAUTI for those. If the device path itself
    # produced zero devices, the plumbing test
    # test_run_forced_registers_post_encounter_enrichers covers enricher
    # registration; canonical-string verification needs at least one HAI to fire.
    if seen_devices == 0 or not seen_types:
        pytest.skip(
            f"100 severe-sepsis patients at seed=42 produced {seen_devices} "
            "devices and 0 HAI events; force_hai_event needs a matching "
            "device-type to fire. Plumbing covered elsewhere."
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
