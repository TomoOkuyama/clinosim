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
        regimen_id="abx-h1-cft",
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


def _vancomycin_regimen() -> AntibioticRegimen:
    """Vancomycin q12h × 14 days = 28 total doses (Issue #1312 test fixture)."""
    return AntibioticRegimen(
        regimen_id="abx-h1-vanc",
        hai_event_id="h1",
        encounter_id="enc-1",
        drug_key="vancomycin",
        dose="1g",
        route="IV",
        frequency="q12h",
        start_datetime=datetime(2026, 1, 10, 8),
        duration_days=14,
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
    assert r.regimen_id == "abx-h1-cft"


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
    # PR-J (2026-07-17): _drug_slug now routes long / underscore-carrying
    # drug names through a FHIR-id-safe override so composed ids stay
    # under the 64-char spec limit. piperacillin_tazobactam → pip-tazo.
    assert ids == {"abx-h2-vanc", "abx-h2-pip-tazo"}


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
        regimen_id="abx-h2-vanc",
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


@pytest.mark.unit
def test_generate_mar_doses_encounter_end_caps_before_snapshot_1312():
    """Issue #1312: when the encounter's discharge_datetime is earlier
    than the snapshot, doses must be truncated at discharge — otherwise
    a 14-day Vancomycin regimen started 3 days pre-discharge emits 11
    doses past ``Encounter.period.end``.

    Vancomycin q12h × 14 days = 28 total doses. If admission → discharge
    spans only 4 days from regimen start, only 8 doses should emit.
    """
    r = _vancomycin_regimen()  # q12h × 14 days from 2026-01-10 08:00
    snapshot = datetime(2026, 12, 31)  # far future — snapshot doesn't clamp
    # Discharge at 2026-01-14 08:00 → doses at 10/08, 10/20, 11/08, 11/20,
    # 12/08, 12/20, 13/08, 13/20, 14/08 = 9 doses fit within the window
    # (the discharge-hour dose is retained; only doses strictly after
    # discharge are dropped). Would be 28 without the cap.
    discharge = datetime(2026, 1, 14, 8)
    mars = generate_mar_doses(
        r,
        snapshot_datetime=snapshot,
        order_id="o-vanc",
        encounter_end_datetime=discharge,
    )
    assert len(mars) == 9, f"expected 9 doses within the 4-day encounter, got {len(mars)} (was 28 before fix)"
    # No dose scheduled after the discharge datetime.
    assert all(m.scheduled_datetime <= discharge for m in mars), (
        f"MAR emitted past discharge: {[m.scheduled_datetime for m in mars if m.scheduled_datetime > discharge]!r}"
    )


@pytest.mark.unit
def test_generate_mar_doses_snapshot_still_caps_when_earlier_than_discharge_1312():
    """Issue #1312 companion: snapshot remains the effective ceiling when
    it's earlier than the encounter discharge (AD-32 semantics preserved)."""
    r = _ceftriaxone_regimen()
    snapshot = datetime(2026, 1, 12, 0)  # only 2 doses fit before snapshot
    discharge = datetime(2026, 1, 20, 0)  # long after snapshot
    mars = generate_mar_doses(
        r,
        snapshot_datetime=snapshot,
        order_id="o-1",
        encounter_end_datetime=discharge,
    )
    # 10 08:00 and 11 08:00 fit; 12 08:00 > snapshot 00:00 → 2 doses.
    assert len(mars) == 2, f"expected 2 doses within snapshot, got {len(mars)}"


@pytest.mark.unit
def test_generate_mar_doses_no_encounter_end_preserves_snapshot_only_behaviour_1312():
    """Issue #1312 backwards-compat: omitting ``encounter_end_datetime``
    (default None) keeps the pre-fix snapshot-only cap so older callers
    and tests are unaffected."""
    r = _ceftriaxone_regimen()
    snapshot = datetime(2026, 12, 31)  # far future
    mars = generate_mar_doses(r, snapshot_datetime=snapshot, order_id="o-1")
    # 7 days × q24h = 7 doses; snapshot doesn't clamp; no encounter cap.
    assert len(mars) == 7
