"""Unit tests for enrich_antibiotic (Phase 3b-1)."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.antibiotic.enricher import enrich_antibiotic
from clinosim.types.encounter import OrderType
from clinosim.types.hai import HAIEvent


def _make_ctx(hai_events):
    rec = SimpleNamespace(
        patient=SimpleNamespace(patient_id="p1"),
        encounters=[],
        orders=[],
        medication_administrations=[],
        microbiology=[],
        extensions={"hai": hai_events},
    )
    cfg = SimpleNamespace(
        country="US",
        snapshot_date=None,
        time_range=("2026-01-01", "2026-12-31"),
    )
    return SimpleNamespace(
        config=cfg,
        master_seed=42,
        records=[rec],
    ), rec


@pytest.mark.unit
def test_enrich_antibiotic_cauti_writes_orders_and_mar():
    ev = HAIEvent(
        hai_id="h1",
        encounter_id="enc-1",
        hai_type="cauti",
        source_device_id="d1",
        icd10_code="",
        snomed_code="",
        onset_date="2026-01-10",
        organism_snomed="",
        culture_specimen_id="",
    )
    ctx, rec = _make_ctx([ev])
    enrich_antibiotic(ctx)
    med_orders = [o for o in rec.orders if o.order_type == OrderType.MEDICATION]
    assert len(med_orders) == 1
    assert med_orders[0].display_name == "Ceftriaxone"
    assert len(rec.medication_administrations) == 7
    assert len(rec.extensions["antibiotic"]) == 1
    r = rec.extensions["antibiotic"][0]
    assert r.drug_key == "Ceftriaxone"
    assert r.hai_event_id == "h1"
    assert r.encounter_id == "enc-1"
    assert r.start_datetime == datetime(2026, 1, 10, 8)


@pytest.mark.unit
def test_enrich_antibiotic_clabsi_emits_two_drugs():
    ev = HAIEvent(
        hai_id="h-clabsi",
        encounter_id="enc-2",
        hai_type="clabsi",
        source_device_id="d1",
        icd10_code="",
        snomed_code="",
        onset_date="2026-02-01",
        organism_snomed="",
        culture_specimen_id="",
    )
    ctx, rec = _make_ctx([ev])
    enrich_antibiotic(ctx)
    med_orders = [o for o in rec.orders if o.order_type == OrderType.MEDICATION]
    assert len(med_orders) == 2
    assert {o.display_name for o in med_orders} == {"Vancomycin", "Piperacillin/Tazobactam"}
    # 14d × (q12h=2 + q6h=4) = 14*2 + 14*4 = 84 MAR
    assert len(rec.medication_administrations) == 84


@pytest.mark.unit
def test_enrich_antibiotic_no_hai_events_no_op():
    ctx, rec = _make_ctx([])
    enrich_antibiotic(ctx)
    assert rec.orders == []
    assert rec.medication_administrations == []
    assert rec.extensions.get("antibiotic", []) == []


@pytest.mark.unit
def test_enrich_antibiotic_missing_extensions_no_crash():
    """A record without extensions["hai"] (e.g. no devices) is a no-op."""
    rec = SimpleNamespace(
        patient=SimpleNamespace(patient_id="p1"),
        encounters=[],
        orders=[],
        medication_administrations=[],
        microbiology=[],
        extensions={},
    )
    cfg = SimpleNamespace(country="US", snapshot_date=None,
                          time_range=("2026-01-01", "2026-12-31"))
    ctx = SimpleNamespace(config=cfg, master_seed=42, records=[rec])
    enrich_antibiotic(ctx)
    assert rec.orders == []
    assert rec.medication_administrations == []


@pytest.mark.unit
def test_enrich_antibiotic_skips_future_onset_hai_ad32():
    """AD-32: HAI events with onset > snapshot must NOT produce orphan Order/MAR.

    inpatient.py:464-490 AD-32 truncation runs AFTER POST_ENCOUNTER stage;
    if antibiotic enricher emits Order+MAR for a HAI event that gets
    truncated, those become orphans. Defensive skip in this enricher
    prevents that.
    """
    # Snapshot defaults to time_range end = 2026-12-31. onset 2027-06-01 is post-snapshot.
    future_ev = HAIEvent(
        hai_id="future-h1",
        encounter_id="enc-1",
        hai_type="cauti",
        source_device_id="d1",
        icd10_code="",
        snomed_code="",
        onset_date="2027-06-01",
        organism_snomed="",
        culture_specimen_id="",
    )
    ctx, rec = _make_ctx([future_ev])
    enrich_antibiotic(ctx)
    assert rec.orders == [], "future-onset HAI must not produce Order"
    assert rec.medication_administrations == [], "future-onset HAI must not produce MAR"
    assert rec.extensions.get("antibiotic", []) == []


@pytest.mark.unit
def test_resolve_snapshot_handles_empty_time_range():
    """PR-93 adversarial review fix: empty time_range tuple must NOT raise."""
    from clinosim.modules.antibiotic.enricher import _resolve_snapshot
    cfg_empty_tuple = SimpleNamespace(snapshot_date=None, time_range=())
    cfg_none = SimpleNamespace(snapshot_date=None, time_range=None)
    cfg_missing = SimpleNamespace(snapshot_date=None)
    cfg_garbage = SimpleNamespace(snapshot_date=None, time_range=("garbage",))
    # All four must return a valid datetime, no IndexError / TypeError
    for cfg in (cfg_empty_tuple, cfg_none, cfg_missing, cfg_garbage):
        out = _resolve_snapshot(cfg)
        assert out == datetime(2099, 12, 31)


@pytest.mark.unit
def test_enrich_antibiotic_present_and_future_hai_mixed():
    """Present-onset HAI emits orders; future-onset HAI in same record is skipped."""
    present_ev = HAIEvent(
        hai_id="present", encounter_id="enc-1", hai_type="cauti",
        source_device_id="d1", icd10_code="", snomed_code="",
        onset_date="2026-01-10", organism_snomed="", culture_specimen_id="",
    )
    future_ev = HAIEvent(
        hai_id="future", encounter_id="enc-1", hai_type="vap",
        source_device_id="d2", icd10_code="", snomed_code="",
        onset_date="2027-06-01", organism_snomed="", culture_specimen_id="",
    )
    ctx, rec = _make_ctx([present_ev, future_ev])
    enrich_antibiotic(ctx)
    assert len(rec.extensions["antibiotic"]) == 1
    assert rec.extensions["antibiotic"][0].hai_event_id == "present"
    assert len([o for o in rec.orders if o.order_type == OrderType.MEDICATION]) == 1
