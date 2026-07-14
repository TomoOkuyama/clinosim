"""FP-UNIFY-2: FHIR dateTime / date helper unit tests.

Centralized helpers `to_fhir_datetime` / `to_fhir_date` normalize
CIF-passthrough datetime values to FHIR R4 dateTime / date spec.

FHIR R4 `dateTime` regex requires 'T' between date and time; the
`str(datetime(...))` fallback that several FHIR builders used produced
space-separated strings ("2024-01-01 08:30:00") which are technically
out-of-spec. Production CIF now writes ISO with `.isoformat()`, but the
latent `str(x)` trap remained in 7 emission sites — this suite pins
helper behavior + normalizes any residual space-separated inputs.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

pytestmark = pytest.mark.unit


class TestToFhirDatetime:
    """session 48 cycle 8 拡張 (feedback FB-F1): TZ 無し文字列に JST +09:00 付与。"""
    def test_datetime_object_isoformat(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_datetime
        # TZ 無し → JST +09:00 付与
        assert to_fhir_datetime(datetime(2024, 1, 1, 8, 30, 0)) == "2024-01-01T08:30:00+09:00"

    def test_iso_str_passthrough(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_datetime
        assert to_fhir_datetime("2024-01-01T08:30:00") == "2024-01-01T08:30:00+09:00"

    def test_space_separated_normalized_to_T(self) -> None:
        """The core fix — str(datetime) space-form must become T-form."""
        from clinosim.modules.output._fhir_common import to_fhir_datetime
        assert to_fhir_datetime("2024-01-01 08:30:00") == "2024-01-01T08:30:00+09:00"

    def test_microseconds_preserved(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_datetime
        assert to_fhir_datetime("2024-01-01T08:30:00.123456") == "2024-01-01T08:30:00.123456+09:00"

    def test_space_separated_with_microseconds_normalized(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_datetime
        assert to_fhir_datetime("2024-01-01 08:30:00.123456") == "2024-01-01T08:30:00.123456+09:00"

    def test_timezone_passthrough(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_datetime
        assert to_fhir_datetime("2024-01-01T08:30:00+09:00") == "2024-01-01T08:30:00+09:00"

    def test_date_only_str_passthrough(self) -> None:
        """A YYYY-MM-DD only value is a valid FHIR dateTime (partial precision)."""
        from clinosim.modules.output._fhir_common import to_fhir_datetime
        assert to_fhir_datetime("2024-01-01") == "2024-01-01"

    def test_date_object_isoformat(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_datetime
        assert to_fhir_datetime(date(2024, 1, 1)) == "2024-01-01"

    def test_none_returns_empty(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_datetime
        assert to_fhir_datetime(None) == ""

    def test_empty_string_passthrough(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_datetime
        assert to_fhir_datetime("") == ""


class TestToFhirDate:
    def test_date_object_isoformat(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_date
        assert to_fhir_date(date(2024, 1, 1)) == "2024-01-01"

    def test_datetime_object_stripped_to_date(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_date
        assert to_fhir_date(datetime(2024, 1, 1, 8, 30, 0)) == "2024-01-01"

    def test_iso_datetime_str_stripped_to_date(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_date
        assert to_fhir_date("2024-01-01T08:30:00") == "2024-01-01"

    def test_space_separated_datetime_str_stripped_to_date(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_date
        assert to_fhir_date("2024-01-01 08:30:00") == "2024-01-01"

    def test_date_only_str_passthrough(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_date
        assert to_fhir_date("2024-01-01") == "2024-01-01"

    def test_none_returns_empty(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_date
        assert to_fhir_date(None) == ""

    def test_empty_string_passthrough(self) -> None:
        from clinosim.modules.output._fhir_common import to_fhir_date
        assert to_fhir_date("") == ""


class TestFhirR4DateTimeRegex:
    """Spec compliance sweep — helper output must match FHIR R4 dateTime regex.

    FHIR R4 dateTime regex (from R4 spec, Appendix Data Types):
      -?[0-9]{4}(-(0[1-9]|1[0-2])(-(0[0-9]|[12][0-9]|3[01])
        (T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)
        (\\.[0-9]+)?(Z|(\\+|-)((0[0-9]|1[0-3]):[0-5][0-9]|14:00))?)?)?)?

    Space-separated forms fail this regex; the T-form passes.
    """

    FHIR_DATETIME_RE = (
        r"^-?[0-9]{4}(-(0[1-9]|1[0-2])(-(0[0-9]|[12][0-9]|3[01])"
        r"(T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)"
        r"(\.[0-9]+)?(Z|(\+|-)((0[0-9]|1[0-3]):[0-5][0-9]|14:00))?)?)?)?$"
    )

    @pytest.mark.parametrize("value", [
        datetime(2024, 1, 1, 8, 30, 0),
        "2024-01-01T08:30:00",
        "2024-01-01 08:30:00",
        "2024-01-01T08:30:00.123456",
        "2024-01-01T08:30:00+09:00",
        "2024-01-01",
        date(2024, 1, 1),
    ])
    def test_output_matches_fhir_regex(self, value: object) -> None:
        import re

        from clinosim.modules.output._fhir_common import to_fhir_datetime
        out = to_fhir_datetime(value)
        assert re.match(self.FHIR_DATETIME_RE, out), (
            f"to_fhir_datetime({value!r}) = {out!r} is not a valid FHIR R4 dateTime"
        )
