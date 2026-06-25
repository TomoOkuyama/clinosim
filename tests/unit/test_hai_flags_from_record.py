"""Unit tests for `hai_flags_from_record` — Phase 3a HAI WBC + CRP lift.

Covers the 3-helper merge architecture (scenario + medication + hai) and the
ramp / encounter-scope / multi-event semantics required by the spec.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from clinosim.modules.physiology.engine import hai_flags_from_record
from clinosim.types.hai import HAIEvent


def _make_event(
    encounter_id: str,
    hai_type: str = "CLABSI",
    onset_date: str = "2026-01-10",
    hai_id: str = "hai-1",
) -> HAIEvent:
    return HAIEvent(
        hai_id=hai_id,
        encounter_id=encounter_id,
        hai_type=hai_type,
        source_device_id="dev-1",
        icd10_code="T80.211A",
        snomed_code="736442006",
        onset_date=onset_date,
        organism_snomed="3092008",
        culture_specimen_id="spec-1",
    )


def _record(events: list[HAIEvent] | None) -> SimpleNamespace:
    extensions = {} if events is None else {"hai": events}
    return SimpleNamespace(extensions=extensions)


@pytest.mark.unit
def test_no_extensions_returns_zero():
    record = SimpleNamespace(extensions={})
    assert hai_flags_from_record(record, "enc-X", date(2026, 1, 12)) == {
        "hai_inflammation_lift": 0.0
    }


@pytest.mark.unit
def test_empty_list_returns_zero():
    assert hai_flags_from_record(_record([]), "enc-X", date(2026, 1, 12)) == {
        "hai_inflammation_lift": 0.0
    }


@pytest.mark.unit
def test_encounter_mismatch_returns_zero():
    record = _record([_make_event("enc-OTHER")])
    assert hai_flags_from_record(record, "enc-X", date(2026, 1, 12)) == {
        "hai_inflammation_lift": 0.0
    }


@pytest.mark.unit
def test_pre_onset_returns_zero():
    record = _record([_make_event("enc-X", onset_date="2026-01-15")])
    assert hai_flags_from_record(record, "enc-X", date(2026, 1, 10)) == {
        "hai_inflammation_lift": 0.0
    }


@pytest.mark.unit
def test_onset_day_clabsi_ramp_zero():
    """day 0 -> ramp_factor = 0/2 = 0.0 -> lift = 0.0"""
    record = _record([_make_event("enc-X", onset_date="2026-01-10")])
    flags = hai_flags_from_record(record, "enc-X", date(2026, 1, 10))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.0)


@pytest.mark.unit
def test_mid_ramp_clabsi_half_lift():
    """day 1 -> ramp_factor = 1/2 = 0.5 -> lift = 0.35 * 0.5 = 0.175"""
    record = _record([_make_event("enc-X", onset_date="2026-01-10")])
    flags = hai_flags_from_record(record, "enc-X", date(2026, 1, 11))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.175)


@pytest.mark.unit
def test_full_lift_clabsi_day_2():
    """day 2 -> ramp_factor = 1.0 -> full lift 0.35"""
    record = _record([_make_event("enc-X", onset_date="2026-01-10")])
    flags = hai_flags_from_record(record, "enc-X", date(2026, 1, 12))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.35)


@pytest.mark.unit
def test_flat_after_peak_no_decay():
    """day 7 -> still 1.0 ramp factor (no decay in Phase 3a)"""
    record = _record([_make_event("enc-X", onset_date="2026-01-10")])
    flags = hai_flags_from_record(record, "enc-X", date(2026, 1, 17))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.35)


@pytest.mark.unit
def test_cauti_lift_value():
    record = _record(
        [_make_event("enc-X", hai_type="CAUTI", onset_date="2026-01-10")]
    )
    flags = hai_flags_from_record(record, "enc-X", date(2026, 1, 12))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.20)


@pytest.mark.unit
def test_vap_lift_value():
    record = _record(
        [_make_event("enc-X", hai_type="VAP", onset_date="2026-01-10")]
    )
    flags = hai_flags_from_record(record, "enc-X", date(2026, 1, 12))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.35)


@pytest.mark.unit
def test_multi_event_takes_max():
    """CLABSI 0.35 + CAUTI 0.20 same encounter day 2 -> max = 0.35"""
    events = [
        _make_event("enc-X", hai_type="CLABSI", onset_date="2026-01-10", hai_id="h1"),
        _make_event("enc-X", hai_type="CAUTI", onset_date="2026-01-10", hai_id="h2"),
    ]
    flags = hai_flags_from_record(_record(events), "enc-X", date(2026, 1, 12))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.35)


@pytest.mark.unit
def test_encounter_id_none_returns_zero():
    record = _record([_make_event("enc-X")])
    assert hai_flags_from_record(record, None, date(2026, 1, 12)) == {
        "hai_inflammation_lift": 0.0
    }


@pytest.mark.unit
def test_current_day_none_returns_zero():
    record = _record([_make_event("enc-X", onset_date="2026-01-10")])
    assert hai_flags_from_record(record, "enc-X", None) == {
        "hai_inflammation_lift": 0.0
    }
