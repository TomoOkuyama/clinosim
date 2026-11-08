"""Pin every input form accepted by ``clinosim.timeutil.parse_iso_datetime`` (Issue #2841)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from clinosim.timeutil import parse_iso_datetime

pytestmark = pytest.mark.unit

_JST = timezone(timedelta(hours=9))


@pytest.mark.parametrize("lenient", [False, True])
class TestBothModes:
    def test_naive_datetime_passthrough(self, lenient: bool) -> None:
        dt = datetime(2025, 3, 4, 5, 6, 7)
        assert parse_iso_datetime(dt, lenient=lenient) is dt

    def test_aware_datetime_passthrough_keeps_tz(self, lenient: bool) -> None:
        dt = datetime(2025, 3, 4, 5, 6, tzinfo=_JST)
        assert parse_iso_datetime(dt, lenient=lenient) is dt

    def test_date_object_is_naive_midnight(self, lenient: bool) -> None:
        assert parse_iso_datetime(date(2025, 3, 4), lenient=lenient) == datetime(2025, 3, 4)

    def test_naive_iso_string(self, lenient: bool) -> None:
        got = parse_iso_datetime("2025-03-04T05:06:07", lenient=lenient)
        assert got == datetime(2025, 3, 4, 5, 6, 7)
        assert got.tzinfo is None

    def test_trailing_z_is_utc(self, lenient: bool) -> None:
        got = parse_iso_datetime("2025-03-04T05:06:07Z", lenient=lenient)
        assert got == datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)
        assert got.utcoffset() == timedelta(0)

    def test_utc_offset_kept(self, lenient: bool) -> None:
        got = parse_iso_datetime("2025-03-04T05:06:07+00:00", lenient=lenient)
        assert got is not None and got.utcoffset() == timedelta(0)

    def test_non_utc_offset_kept_not_converted(self, lenient: bool) -> None:
        got = parse_iso_datetime("2025-03-04T05:06:07+09:00", lenient=lenient)
        assert got is not None
        assert (got.hour, got.utcoffset()) == (5, timedelta(hours=9))

    def test_date_only_string_is_naive_midnight(self, lenient: bool) -> None:
        got = parse_iso_datetime("2025-03-04", lenient=lenient)
        assert got == datetime(2025, 3, 4)
        assert got.tzinfo is None

    @pytest.mark.parametrize("value", [None, "", "not a date", "2025-13-01", 20250304, 1.5, ["2025-03-04"]])
    def test_absent_or_garbage_is_none(self, lenient: bool, value: object) -> None:
        assert parse_iso_datetime(value, lenient=lenient) is None


def test_strict_rejects_surrounding_whitespace() -> None:
    assert parse_iso_datetime(" 2025-03-04T05:06:07 ") is None
    assert parse_iso_datetime("   ") is None


def test_lenient_strips_surrounding_whitespace() -> None:
    assert parse_iso_datetime(" 2025-03-04T05:06:07 ", lenient=True) == datetime(2025, 3, 4, 5, 6, 7)
    assert parse_iso_datetime("   ", lenient=True) is None


def test_strict_rejects_trailing_garbage() -> None:
    assert parse_iso_datetime("2025-03-04 garbage") is None


def test_lenient_falls_back_to_leading_date() -> None:
    assert parse_iso_datetime("2025-03-04 garbage", lenient=True) == datetime(2025, 3, 4)
    assert parse_iso_datetime("garbage-2025-03-04", lenient=True) is None
