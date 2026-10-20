"""Phase 4a — event pattern meds path (dedup + modifier + lookup).

Tests `EventSpec.emits_meds` + `fire_marker` extension and the step() dedup
and med_additions population behavior.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.patterns.event import EventSpec, step


def test_event_spec_emits_meds_default_empty():
    spec = EventSpec(
        event_name="x",
        emits_icd="E11.21",
        base_annual_rate=1.0,
        rate_modifiers=[],
        one_shot=True,
    )
    assert spec.emits_meds == []
    assert spec.fire_marker == ""


def test_event_spec_rejects_fully_empty_event():
    """Both emits_icd and emits_meds empty = yaml authoring error."""
    with pytest.raises(ValueError):
        EventSpec(
            event_name="x",
            emits_icd="",
            base_annual_rate=1.0,
            rate_modifiers=[],
            one_shot=True,
        )


def test_event_spec_accepts_med_only_event():
    """emits_icd empty + emits_meds populated = valid med-only event."""
    spec = EventSpec(
        event_name="dm_escalate_sglt2i",
        emits_icd="",
        emits_meds=["Empagliflozin"],
        fire_marker="dm_escalate_sglt2i",
        base_annual_rate=1.0,
        rate_modifiers=[],
        one_shot=True,
    )
    assert spec.emits_meds == ["Empagliflozin"]
    assert spec.fire_marker == "dm_escalate_sglt2i"


def test_step_med_only_fire_populates_med_additions():
    """When the event fires and emits_meds is non-empty,
    EventResult.med_additions == spec.emits_meds."""
    spec = EventSpec(
        event_name="x",
        emits_icd="",
        emits_meds=["Empagliflozin"],
        fire_marker="x",
        base_annual_rate=1.0,
        rate_modifiers=[],
        one_shot=True,
    )
    rng = np.random.default_rng(0)
    result = step([], [], rng, spec, context={})
    assert result.fired
    assert result.emits_icd == ""
    assert result.med_additions == ["Empagliflozin"]


def test_step_med_only_no_fire_returns_empty_med_additions():
    spec = EventSpec(
        event_name="x",
        emits_icd="",
        emits_meds=["Empagliflozin"],
        fire_marker="x",
        base_annual_rate=0.0,
        rate_modifiers=[],
        one_shot=True,
    )
    rng = np.random.default_rng(0)
    result = step([], [], rng, spec, context={})
    assert not result.fired
    assert result.med_additions == []


def test_event_spec_rejects_unknown_field():
    """extra='forbid' still applies — a typo'd field is a loud failure."""
    with pytest.raises(ValueError):
        EventSpec(
            event_name="x",
            emits_icd="E11.21",
            typo_field="oops",
            base_annual_rate=1.0,
            rate_modifiers=[],
            one_shot=True,
        )


def test_step_med_only_one_shot_dedup_against_prior_med_additions():
    """Review Focus #1: a med-only event that fired last year must not
    re-fire this year, even at p=1.0."""
    from clinosim.modules.longitudinal.snapshot import YearSnapshot

    spec = EventSpec(
        event_name="dm_escalate_sglt2i",
        emits_icd="",
        emits_meds=["Empagliflozin"],
        fire_marker="dm_escalate_sglt2i",
        base_annual_rate=1.0,
        rate_modifiers=[],
        one_shot=True,
    )
    rng = np.random.default_rng(0)
    prior = [YearSnapshot(year=2024, med_additions=["dm_escalate_sglt2i"])]
    result = step([], prior, rng, spec, context={})
    assert not result.fired
    assert result.med_additions == []


def test_step_med_only_dedup_requires_fire_marker():
    """Without fire_marker set, med-only event has no dedup key and
    will re-fire every year — the yaml author must set fire_marker."""
    from clinosim.modules.longitudinal.snapshot import YearSnapshot

    spec = EventSpec(
        event_name="x",
        emits_icd="",
        emits_meds=["Empagliflozin"],
        fire_marker="",  # intentionally empty
        base_annual_rate=1.0,
        rate_modifiers=[],
        one_shot=True,
    )
    rng = np.random.default_rng(0)
    prior = [YearSnapshot(year=2024, med_additions=["Empagliflozin"])]
    result = step([], prior, rng, spec, context={})
    # Without a dedup key, event still fires — this is intentional
    # (Phase 4a's yamls always set fire_marker; this test pins that
    # the engine does not silently invent one).
    assert result.fired


def test_step_med_only_dedup_does_not_affect_icd_only_events():
    """ICD-only events keep their Phase 3 dedup via emits_icd — the
    new fire_marker logic doesn't interfere."""
    from clinosim.modules.longitudinal.snapshot import YearSnapshot

    spec = EventSpec(
        event_name="x",
        emits_icd="E11.21",
        base_annual_rate=1.0,
        rate_modifiers=[],
        one_shot=True,
    )
    rng = np.random.default_rng(0)
    prior = [YearSnapshot(year=2024, new_complications=["E11.21"])]
    result = step([], prior, rng, spec, context={})
    assert not result.fired
