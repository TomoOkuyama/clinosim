"""Unit tests for engine.build_regimens + generate_mar_doses (Phase 3b-1)."""
from datetime import datetime

import pytest

from clinosim.modules.antibiotic.engine import (
    FREQ_PER_DAY,
    build_regimens,
    generate_mar_doses,
)
from clinosim.types.antibiotic import AntibioticRegimen
from clinosim.types.hai import HAIEvent


def _make_event(hai_type: str, hai_id: str = "h1", enc_id: str = "enc-1") -> HAIEvent:
    return HAIEvent(
        hai_id=hai_id,
        encounter_id=enc_id,
        hai_type=hai_type,
        source_device_id="d1",
        icd10_code="",
        snomed_code="",
        onset_date="2026-01-10",
        organism_snomed="",
        culture_specimen_id="",
    )


def _ceftriaxone_regimen() -> AntibioticRegimen:
    return AntibioticRegimen(
        regimen_id="abx-h1-ceftriaxone",
        hai_event_id="h1",
        encounter_id="enc-1",
        drug_key="ceftriaxone",
        dose="1g",
        route="IV",
        frequency="q24h",
        start_datetime=datetime(2026, 1, 10, 8),
        duration_days=7,
        intent="empirical",
    )


# ===== Task 3 — build_regimens =====


@pytest.mark.unit
def test_build_regimens_cauti_single_drug():
    ev = _make_event("cauti")
    regs = build_regimens(ev, start_datetime=datetime(2026, 1, 10, 8))
    assert len(regs) == 1
    r = regs[0]
    assert r.hai_event_id == "h1"
    assert r.encounter_id == "enc-1"
    assert r.drug_key == "ceftriaxone"
    assert r.dose == "1g"
    assert r.route == "IV"
    assert r.frequency == "q24h"
    assert r.start_datetime == datetime(2026, 1, 10, 8)
    assert r.duration_days == 7
    assert r.intent == "empirical"
    assert r.regimen_id == "abx-h1-ceftriaxone"


@pytest.mark.unit
def test_build_regimens_clabsi_two_drugs():
    ev = _make_event("clabsi", hai_id="h2")
    regs = build_regimens(ev, start_datetime=datetime(2026, 2, 1, 8))
    drug_keys = {r.drug_key for r in regs}
    assert drug_keys == {"vancomycin", "piperacillin_tazobactam"}
    for r in regs:
        assert r.duration_days == 14
        assert r.start_datetime == datetime(2026, 2, 1, 8)
        assert r.hai_event_id == "h2"
    ids = {r.regimen_id for r in regs}
    assert ids == {"abx-h2-vancomycin", "abx-h2-piperacillin_tazobactam"}


@pytest.mark.unit
def test_build_regimens_vap_two_drugs_7d():
    ev = _make_event("vap", hai_id="h3", enc_id="enc-9")
    regs = build_regimens(ev, start_datetime=datetime(2026, 3, 15, 8))
    assert len(regs) == 2
    for r in regs:
        assert r.duration_days == 7
        assert r.encounter_id == "enc-9"


@pytest.mark.unit
def test_build_regimens_unknown_hai_type_raises():
    ev = _make_event("bogus_hai")
    with pytest.raises(KeyError):
        build_regimens(ev, start_datetime=datetime(2026, 1, 1))


# ===== Task 4 — generate_mar_doses =====


@pytest.mark.unit
def test_freq_per_day_table_is_canonical():
    assert FREQ_PER_DAY == {"q24h": 1, "q12h": 2, "q8h": 3, "q6h": 4, "q4h": 6}


@pytest.mark.unit
def test_generate_mar_doses_ceftriaxone_q24h_7days_no_truncation():
    r = _ceftriaxone_regimen()
    snapshot = datetime(2026, 12, 31)
    mars = generate_mar_doses(r, snapshot_datetime=snapshot, order_id="o-1")
    assert len(mars) == 7
    assert mars[0].scheduled_datetime == datetime(2026, 1, 10, 8)
    assert mars[-1].scheduled_datetime == datetime(2026, 1, 16, 8)
    for m in mars:
        assert m.drug_name == "Ceftriaxone"
        assert m.dose == "1g"
        assert m.route == "IV"
        assert m.status == "given"
        assert m.order_id == "o-1"


@pytest.mark.unit
def test_generate_mar_doses_vancomycin_q12h_14days():
    r = AntibioticRegimen(
        regimen_id="abx-h2-vancomycin",
        hai_event_id="h2",
        encounter_id="enc-2",
        drug_key="vancomycin",
        dose="1g",
        route="IV",
        frequency="q12h",
        start_datetime=datetime(2026, 1, 10, 8),
        duration_days=14,
        intent="empirical",
    )
    snapshot = datetime(2026, 12, 31)
    mars = generate_mar_doses(r, snapshot_datetime=snapshot, order_id="o-2")
    assert len(mars) == 14 * 2
    assert mars[0].scheduled_datetime == datetime(2026, 1, 10, 8)
    assert mars[1].scheduled_datetime == datetime(2026, 1, 10, 20)
    assert mars[2].scheduled_datetime == datetime(2026, 1, 11, 8)


@pytest.mark.unit
def test_generate_mar_doses_pip_tazo_q6h_14days():
    r = AntibioticRegimen(
        regimen_id="abx-h3-pip",
        hai_event_id="h3",
        encounter_id="enc-3",
        drug_key="piperacillin_tazobactam",
        dose="3.375g",
        route="IV",
        frequency="q6h",
        start_datetime=datetime(2026, 1, 10, 8),
        duration_days=14,
        intent="empirical",
    )
    mars = generate_mar_doses(r, snapshot_datetime=datetime(2026, 12, 31), order_id="o-3")
    assert len(mars) == 14 * 4
    assert mars[0].scheduled_datetime == datetime(2026, 1, 10, 8)
    assert mars[1].scheduled_datetime == datetime(2026, 1, 10, 14)
    assert mars[2].scheduled_datetime == datetime(2026, 1, 10, 20)
    assert mars[3].scheduled_datetime == datetime(2026, 1, 11, 2)


@pytest.mark.unit
def test_generate_mar_doses_snapshot_truncates():
    r = _ceftriaxone_regimen()  # 7 days starting 2026-01-10 08:00
    snapshot = datetime(2026, 1, 13, 0)  # mid-day 3 → only 3 doses fit (10/11/12 at 08:00)
    mars = generate_mar_doses(r, snapshot_datetime=snapshot, order_id="o-1")
    assert len(mars) == 3
    assert mars[-1].scheduled_datetime == datetime(2026, 1, 12, 8)


@pytest.mark.unit
def test_generate_mar_doses_unknown_frequency_raises():
    r = _ceftriaxone_regimen()
    r.frequency = "q99h"
    with pytest.raises(KeyError):
        generate_mar_doses(r, snapshot_datetime=datetime(2026, 12, 31), order_id="o-1")
