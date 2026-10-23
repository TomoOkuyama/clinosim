"""Issue #1754: statin high-intensity escalation must substitute, not stack.

Pre-fix the Phase 4b.1 ``lipid_escalate_high_intensity_e78`` event
emitted Rosuvastatin (high-intensity statin) into
``person.current_medications`` without retracting the baseline
Atorvastatin from the E78 chronic regimen. The result was 14.7 % of
the p=10k 5y US cohort carrying BOTH statins — a well-established
therapeutic duplication contraindicated by ACC/AHA 2018 Cholesterol
Guideline (increased myopathy / rhabdomyolysis risk, no added LDL
benefit).

Fix: declare ``removes_meds: ["Atorvastatin"]`` on the event yaml and
teach the longitudinal engine to retract named drugs from
``person.current_medications`` when an event fires (same code-path
that already extends ``snapshot.med_removals``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml as _yaml

from clinosim.modules.longitudinal.patterns.event import EventResult, EventSpec
from clinosim.modules.longitudinal.patterns.event import step as fire_event

pytestmark = pytest.mark.unit

_YAML = (
    Path(__file__).resolve().parents[1].parent
    / "clinosim"
    / "locale"
    / "shared"
    / "longitudinal"
    / "med"
    / "lipid_escalate_high_intensity_e78.yaml"
)


def _load_spec() -> EventSpec:
    with _YAML.open(encoding="utf-8") as fh:
        raw = _yaml.safe_load(fh) or {}
    # Only the EventSpec-shaped keys (strip pattern + clinical_scope).
    keep = {
        "event_name",
        "emits_icd",
        "emits_meds",
        "removes_meds",
        "fire_marker",
        "base_annual_rate",
        "base_rate_by_age_band",
        "rate_modifiers",
        "one_shot",
    }
    return EventSpec(**{k: v for k, v in raw.items() if k in keep})


# ----------------------------------------------------------------------------
# EventSpec schema accepts removes_meds
# ----------------------------------------------------------------------------


def test_event_spec_accepts_removes_meds_field() -> None:
    """EventSpec was ``extra='forbid'`` pre-fix — new ``removes_meds``
    field must be formally declared."""
    spec = EventSpec(event_name="x", emits_icd="", emits_meds=["Rosuvastatin"], removes_meds=["Atorvastatin"])
    assert spec.removes_meds == ["Atorvastatin"]


def test_event_spec_defaults_removes_meds_to_empty() -> None:
    """Backwards-compat: an event yaml with no removes_meds field
    parses and defaults to an empty list — every pre-fix yaml carries
    this shape and must keep working."""
    spec = EventSpec(event_name="x", emits_icd="", emits_meds=["Y"])
    assert spec.removes_meds == []


# ----------------------------------------------------------------------------
# fire_event returns removes_meds on fired path, empty on skipped path
# ----------------------------------------------------------------------------


def test_fire_event_propagates_removes_meds_to_result() -> None:
    """When the event fires, EventResult.med_removals carries the
    yaml's ``removes_meds`` verbatim."""
    spec = EventSpec(
        event_name="e",
        emits_icd="",
        emits_meds=["Rosuvastatin"],
        removes_meds=["Atorvastatin"],
        base_annual_rate=1.0,  # always fires
    )
    rng = np.random.default_rng(42)
    result: EventResult = fire_event(["E78"], [], rng, spec)
    assert result.fired
    assert result.med_additions == ["Rosuvastatin"]
    assert result.med_removals == ["Atorvastatin"]


def test_fire_event_skipped_still_returns_empty_removals() -> None:
    """When the event does not fire, med_removals is empty — the engine
    only retracts drugs on a successful fire."""
    spec = EventSpec(
        event_name="e",
        emits_icd="",
        emits_meds=["Rosuvastatin"],
        removes_meds=["Atorvastatin"],
        base_annual_rate=0.0,  # never fires
    )
    rng = np.random.default_rng(42)
    result = fire_event(["E78"], [], rng, spec)
    assert not result.fired
    assert result.med_removals == []


# ----------------------------------------------------------------------------
# Yaml is wired correctly
# ----------------------------------------------------------------------------


def test_lipid_escalate_yaml_declares_atorvastatin_removal() -> None:
    """The lipid high-intensity escalation yaml carries the fix — a
    retrievable pin against future accidental retirement."""
    spec = _load_spec()
    assert spec.emits_meds == ["Rosuvastatin"]
    assert spec.removes_meds == ["Atorvastatin"]
