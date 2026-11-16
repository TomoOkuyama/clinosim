"""Run-summary length of stay comes from the encounter datetimes (#3225).

Delivery and newborn stays carry no daily physiological states, so the old
``len(physiological_states) - 1`` proxy printed ``LOS avg -1.0d`` for them.
"""

from __future__ import annotations

from datetime import datetime

from clinosim.simulator.cli_common import _encounter_los_days, _print_debug_record, _print_summary
from clinosim.types.clinical import ConditionEvent
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFDataset, CIFPatientRecord


def _record(code: str, admit: datetime, discharge: datetime | None, n_states: int = 0) -> CIFPatientRecord:
    return CIFPatientRecord(
        encounters=[
            Encounter(
                encounter_id=f"ENC-{code}",
                encounter_type=EncounterType.INPATIENT,
                admission_datetime=admit,
                discharge_datetime=discharge,
            )
        ],
        condition_event=ConditionEvent(ground_truth_diseases=[code]),
        physiological_states=[object()] * n_states,  # type: ignore[list-item]
    )


def test_los_uses_calendar_dates_without_physiological_states() -> None:
    rec = _record("Z37.0", datetime(2026, 1, 9, 10, 24), datetime(2026, 1, 13, 10, 24))
    assert _encounter_los_days(rec) == 4


def test_los_counts_calendar_days_not_24h_blocks() -> None:
    rec = _record("Z38.0", datetime(2026, 1, 9, 22, 0), datetime(2026, 1, 11, 8, 0))
    assert _encounter_los_days(rec) == 2


def test_los_same_day_stay_counts_one_day() -> None:
    rec = _record("Z38.0", datetime(2026, 1, 9, 8, 0), datetime(2026, 1, 9, 20, 0))
    assert _encounter_los_days(rec) == 1


def test_los_in_progress_falls_back_to_states() -> None:
    rec = _record("J18.9", datetime(2026, 1, 9, 8, 0), None, n_states=6)
    assert _encounter_los_days(rec) == 5


def test_los_none_without_encounter() -> None:
    assert _encounter_los_days(CIFPatientRecord()) is None


def test_summary_reports_non_negative_los_for_stays_without_states(capsys) -> None:
    ds = CIFDataset(
        patients=[
            _record("Z37.0", datetime(2026, 1, 9, 10, 0), datetime(2026, 1, 11, 9, 0)),
            _record("Z37.0", datetime(2026, 2, 1, 3, 0), datetime(2026, 2, 3, 12, 0)),
        ]
    )
    _print_summary(ds, "out")
    out = capsys.readouterr().out
    assert "LOS avg 2.0d" in out
    assert "-1.0d" not in out


def test_debug_record_prints_delivery_los(capsys) -> None:
    rec = _record("Z37.0", datetime(2026, 1, 9, 10, 24), datetime(2026, 1, 13, 10, 24))
    _print_debug_record(rec)
    assert "LOS: 4 days" in capsys.readouterr().out
