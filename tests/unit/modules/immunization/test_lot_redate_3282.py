"""Issue #3282: a re-dated dose carries a lot of its new date.

The synthetic lot number ``L<MFR>-<YYYYMM>-<BATCH>`` embeds the month of the
dose. Every path that moves ``occurrence_date`` (the vaccination-visit
binding, the nearest-encounter alignment and the clinic-day hold) regenerates
the lot for the new date, so no lot is dated after its administration.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.immunization.engine import (
    load_schedule,
    lot_cvx_by_cvx,
    redate,
    synthetic_lot_number,
)
from clinosim.modules.immunization.enricher import _align_to_encounters
from clinosim.types.encounter import ImmunizationRecord

pytestmark = pytest.mark.unit


def _lot_month(lot: str) -> str:
    return lot.split("-")[1]


def test_redate_regenerates_the_lot_of_a_given_dose() -> None:
    imm = ImmunizationRecord(
        vaccine_cvx="140",
        occurrence_date=date(2026, 11, 2),
        lot_number=synthetic_lot_number("150", date(2026, 11, 2)),
    )
    redate(imm, date(2026, 10, 30), "150")
    assert imm.occurrence_date == date(2026, 10, 30)
    assert imm.lot_number == synthetic_lot_number("150", date(2026, 10, 30))


def test_redate_leaves_a_declined_dose_without_a_lot() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 11, 2), status="not-done")
    redate(imm, date(2026, 10, 30), "150")
    assert imm.occurrence_date == date(2026, 10, 30)
    assert not imm.lot_number


def test_lot_key_is_the_schedule_entry_cvx_for_every_product() -> None:
    # US influenza: entry CVX 150, products 140 / 150 (the lot's manufacturer
    # is derived from the entry, as at generation).
    keys = lot_cvx_by_cvx(load_schedule("US"))
    assert keys["140"] == "150"
    assert keys["150"] == "150"


def test_alignment_snaps_the_lot_with_the_date() -> None:
    given = date(2026, 9, 2)
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=given, lot_number=synthetic_lot_number("150", given))
    enc = SimpleNamespace(
        encounter_id="enc-a", admission_datetime=datetime(2026, 8, 20, 10), encounter_type="outpatient"
    )
    [out] = _align_to_encounters([imm], [enc], lot_cvx=lot_cvx_by_cvx(load_schedule("US")))
    assert out.occurrence_date == date(2026, 8, 20)
    assert out.lot_number == synthetic_lot_number("150", date(2026, 8, 20))
    assert _lot_month(out.lot_number) == "202608"


def test_clinic_day_hold_back_into_the_previous_month_relots(monkeypatch) -> None:
    from clinosim.modules.immunization.enricher import enrich_immunizations
    from tests.unit.modules.immunization.test_companion_vaccination_encounter import (
        _mk_record,
        _StubConfig,
        _StubCtx,
    )

    # 2026-11-01 is a Sunday and the record's as-of date: the dose is held on
    # Saturday 31 October, and its lot is of October.
    due = date(2026, 11, 1)
    monkeypatch.setattr(
        "clinosim.modules.immunization.enricher.generate_immunizations",
        lambda *_a, **_k: [
            ImmunizationRecord(vaccine_cvx="140", occurrence_date=due, lot_number=synthetic_lot_number("140", due))
        ],
    )
    monkeypatch.setattr("clinosim.modules.immunization.enricher.load_schedule", lambda country: {})
    ctx = _StubCtx()
    ctx.config = _StubConfig(country="US", time_range=("2025-11-02", "2026-11-01"), snapshot_date="2026-11-01")
    ctx.records = [_mk_record("pt-x", [])]
    enrich_immunizations(ctx)
    [imm] = ctx.records[0].immunizations
    assert imm.occurrence_date == date(2026, 10, 31)
    assert imm.lot_number == synthetic_lot_number("140", date(2026, 10, 31))
