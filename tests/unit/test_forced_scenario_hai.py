"""Unit tests for ForcedScenario.force_hai_event (PR3b-1 Task 7b)."""
from datetime import date
from types import SimpleNamespace

import pytest

from clinosim.types.config import ForcedScenario


@pytest.mark.unit
def test_forced_scenario_default_no_force_hai():
    s = ForcedScenario(disease_id="sepsis")
    assert s.force_hai_event is None


@pytest.mark.unit
def test_forced_scenario_force_hai_event_dict():
    s = ForcedScenario(
        disease_id="sepsis",
        force_hai_event={
            "hai_type": "cauti",
            "onset_offset_days": 3,
            "organism_snomed": "112283007",
        },
    )
    assert s.force_hai_event["hai_type"] == "cauti"
    assert s.force_hai_event["onset_offset_days"] == 3
    assert s.force_hai_event["organism_snomed"] == "112283007"


@pytest.mark.unit
def test_forced_scenario_force_hai_event_missing_hai_type_accepted_at_dataclass():
    """Consumer (enrich_hai) is expected to validate hai_type ∈ HAI_TYPES;
    the dict itself accepts arbitrary shape so legacy callers don't break."""
    s = ForcedScenario(disease_id="sepsis", force_hai_event={"hai_type": "bogus"})
    assert s.force_hai_event["hai_type"] == "bogus"


from clinosim.modules.hai.enricher import enrich_hai
from clinosim.types.device import DeviceRecord


def _make_ctx_with_device(device_type: str, force_hai_event: dict | None):
    dev = DeviceRecord(
        device_id="d1",
        encounter_id="enc-1",
        device_type=device_type,
        snomed_code="23973005",
        placement_date="2026-01-05",
        removal_date="2026-01-15",
        placement_indication="test",
    )
    rec = SimpleNamespace(
        patient=SimpleNamespace(patient_id="p1"),
        extensions={"device": [dev]},
        microbiology=[],
    )
    forced = SimpleNamespace(
        disease_id="urinary_tract_infection", count=1, severity=None,
        archetype=None, complications=[], patient_overrides={},
        force_hai_event=force_hai_event,
    )
    cfg = SimpleNamespace(
        country="US", random_seed=42,
        time_range=("2026-01-01", "2026-12-31"),
        snapshot_date=None,
        forced_scenarios=[forced],
    )
    return SimpleNamespace(config=cfg, master_seed=42, records=[rec]), rec


@pytest.mark.unit
def test_enrich_hai_force_emits_one_event_per_matching_device():
    """force_hai_event with hai_type=cauti emits HAI for indwelling_catheter
    devices, ignoring Poisson sampling."""
    ctx, rec = _make_ctx_with_device(
        device_type="indwelling_catheter",
        force_hai_event={
            "hai_type": "cauti",
            "onset_offset_days": 3,
            "organism_snomed": "112283007",
        },
    )
    enrich_hai(ctx)
    hai = rec.extensions.get("hai", []) or []
    assert len(hai) == 1
    assert hai[0].hai_type == "cauti"
    assert hai[0].onset_date == "2026-01-08"  # placement 2026-01-05 + 3 days
    assert hai[0].organism_snomed == "112283007"


@pytest.mark.unit
def test_enrich_hai_force_mismatched_hai_type_no_emit():
    """force_hai_event with hai_type=vap but only catheter device → no emit."""
    ctx, rec = _make_ctx_with_device(
        device_type="indwelling_catheter",  # CAUTI mapping, not VAP
        force_hai_event={
            "hai_type": "vap",
            "onset_offset_days": 3,
            "organism_snomed": "3092008",
        },
    )
    enrich_hai(ctx)
    assert rec.extensions.get("hai", []) == []
